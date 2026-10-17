"""Explicitly invoked diagnostic command line interface."""
import argparse
import json
from pathlib import Path
import sys
import urllib.error

from .client import Client
from .settings import Settings, config



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--login', action='store_true', help='Explicit login: may displace browser session')
    parser.add_argument('--cookie-file', default='.local/session.cookies')
    parser.add_argument('--serial', help='Override SUPERWISE_SERIAL_NUMBER for this invocation')
    parser.add_argument('--listen', type=int, default=0, metavar='SECONDS')
    parser.add_argument('--history', action='store_true', help='Include latest listed firing curves')
    parser.add_argument('--output', default='artifacts/snapshot.json')
    args = parser.parse_args()
    if args.listen < 0:
        parser.error('--listen must be nonnegative')
    cfg = config()
    try:
        settings = Settings.from_mapping(cfg, args.serial)
    except ValueError as exc:
        parser.error(str(exc))
    client = Client(settings.url, args.cookie_file, settings.rated_power_kw)
    if args.login:
        if not settings.username or not settings.password:
            parser.error('Set SUPERWISE_USERNAME and SUPERWISE_PASSWORD in .env or environment')
        client.login(settings.username, settings.password)
    elif not client.cookie_path.exists():
        parser.error('No saved session. Use --login once; this may displace the browser session.')
    result = client.snapshot(settings.serial_number)
    serial = result['controller']['serialNumber']
    if args.history and result['firings']:
        result['latest_firing_history'] = client.history(
            serial, result['firings'][0], [s['identifier'] for s in result['sensors']])
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps(result['controller'], ensure_ascii=False, allow_nan=False))
    if args.listen:
        count = 0
        with output.with_suffix('.live.jsonl').open('w') as stream:
            for message in client.listen(serial, args.listen):
                line = json.dumps(message, ensure_ascii=False, allow_nan=False)
                stream.write(line + '\n')
                stream.flush()
                print(line, flush=True)
                count += 1
        print(f'Live messages received: {count}')
    print(f'Snapshot: {output}')



def run():
    try:
        main()
    except (RuntimeError, ValueError, OSError, urllib.error.URLError) as exc:
        print(f"Probe stopped ({type(exc).__name__}). Session is not renewed automatically.", file=sys.stderr)
        return 1
    return 0
