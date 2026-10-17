"""Read-only HTTP and SockJS/STOMP transport; no automatic reauthentication."""
import http.cookiejar
import json
import os
from pathlib import Path
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import datetime as dt

from .models import embedded, controller_summary, sensor_summary, live_summary, pick


class SessionExpired(RuntimeError):
    pass



class Client:
    def __init__(self, base, cookie_path, rated_power_kw=None):
        self.rated_power_kw = rated_power_kw
        if '://' not in base:
            base = 'https://' + base
        # The bare host redirects to www; POST redirects can lose their body.
        if base.rstrip('/') == 'https://superwise.eu':
            base = 'https://www.superwise.eu'
        parsed = urllib.parse.urlsplit(base)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('SUPERWISE_URL must be an HTTPS URL without credentials')
        if parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            raise ValueError('SUPERWISE_URL must be the site origin')
        self.base = base.rstrip('/')
        self.cookie_path = Path(cookie_path)
        self.jar = http.cookiejar.LWPCookieJar(str(self.cookie_path))
        if self.cookie_path.exists():
            self.jar.load(ignore_discard=True)
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def request(self, path, data=None, content_type=None, login=False, timeout=25):
        headers = {'User-Agent': 'superwise-readonly-research/0.1'}
        if content_type:
            headers['Content-Type'] = content_type
        request = urllib.request.Request(self.base + path, data=data, headers=headers)
        try:
            response = self.opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise SessionExpired('Session unavailable. Stopped; no automatic login.') from None
            raise RuntimeError(f'Superwise HTTP {exc.code}') from None
        with response:
            body = response.read().decode('utf-8')
            if not login and (urllib.parse.urlsplit(response.url).path == '/login'
                              or 'id="login-button"' in body):
                raise SessionExpired('Session expired or replaced. Stopped; no automatic login.')
            return body

    def login(self, username, password):
        self.request('/login', login=True)
        self.request('/login', urllib.parse.urlencode({
            'username': username, 'password': password}).encode(),
            'application/x-www-form-urlencoded', login=True)
        self.request('/dashboard')  # verify before saving
        self.cookie_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.cookie_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.close(fd)
        os.chmod(self.cookie_path, 0o600)
        self.jar.save(ignore_discard=True)

    def snapshot(self, serial=None):
        dashboard = self.request('/dashboard')
        controllers = embedded(dashboard, 'controllers')['content']
        if not controllers:
            raise RuntimeError('No paired controller found')
        if serial is None:
            if len(controllers) != 1:
                raise ValueError('Multiple controllers: specify --serial')
            serial = controllers[0]['serialNumber']
        if serial not in [c['serialNumber'] for c in controllers]:
            raise ValueError('Requested controller is not in this account')
        serial = str(serial)
        if not serial.isdigit():
            raise ValueError('Invalid controller serial')
        view = self.request(f'/controller/{serial}/view')
        programs = embedded(self.request(f'/program/{serial}'), 'programs')
        firings = embedded(self.request('/firings'), 'firings')
        return {
            'observed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'controller': controller_summary(embedded(view, 'controlUnit'), self.rated_power_kw),
            'online_status': self.request(f'/controller/{serial}/onlinestatus'),
            'sensors': [sensor_summary(s) for s in embedded(view, 'sensors')],
            'programs': [dict(number=p['number'], definition=json.loads(p['payload'])) for p in programs],
            'firings': [pick(f, ('id', 'serialNumber', 'status', 'programName', 'programNumber',
                                'startAt', 'endAt', 'recording')) for f in firings
                        if f['serialNumber'] == serial],
            'alarms': {'active_page_entries': len(embedded(view, 'alarms')),
                       'process_page_entries': len(embedded(view, 'prcsAlarms'))},
        }

    def history(self, serial, firing, identifiers):
        start, end = firing.get('startAt'), firing.get('endAt')
        if start is None or end is None:
            raise ValueError('Latest firing has no complete time range')
        return {identifier: json.loads(self.request(
            f'/controller/{serial}/{identifier}/chartdata/{start}/{end}/0'))
                for identifier in identifiers if re.fullmatch(r'[A-Z]+[0-9]*', identifier)}

    def listen(self, serial, seconds):
        # SockJS XHR transport uses the same STOMP destination as the website.
        self.request('/ws/info')
        endpoint = '/ws/000/' + uuid.uuid4().hex

        def send(frame):
            self.request(endpoint + '/xhr_send', json.dumps([frame]).encode(), 'application/json')

        def receive(timeout=20):
            reply = self.request(endpoint + '/xhr', b'', 'application/json', timeout=timeout).strip()
            if reply.startswith('c'):
                raise SessionExpired('Live connection closed. Stopped; no automatic login.')
            return json.loads(reply[1:]) if reply.startswith('a') else []

        deadline = time.monotonic() + seconds
        receive()
        send('CONNECT\naccept-version:1.1,1.0\nheart-beat:0,0\n\n\x00')
        try:
            while time.monotonic() < deadline:
                try:
                    frames = receive(max(0.1, min(20, deadline - time.monotonic())))
                except (TimeoutError, socket.timeout):
                    # A timed-out XHR may still exist server-side. End this connection.
                    break
                for frame in frames:
                    if frame.startswith('CONNECTED'):
                        send(f'SUBSCRIBE\nid:probe-0\ndestination:/topic/{serial}/data\n\n\x00')
                    elif frame.startswith('MESSAGE'):
                        yield live_summary(json.loads(frame.split('\n\n', 1)[1].rstrip('\x00')),
                                           self.rated_power_kw)
                    elif frame.startswith('ERROR'):
                        raise RuntimeError('STOMP server rejected the subscription')
        finally:
            try:
                send('DISCONNECT\n\n\x00')
            except (RuntimeError, OSError):
                pass

