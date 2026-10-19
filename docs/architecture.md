# Architecture

## Home Assistant custom integration

All runtime files reside under `custom_components/superwise/` so HACS/manual
installation does not depend on the diagnostic package at repository root.

- `api.py`: asynchronous HTTP and SockJS/STOMP using an isolated cookie session.
  Same-origin redirects only; a same-host HTTP login redirect is upgraded locally
  to HTTPS before any request. No implicit authentication or command retries.
- `config_flow.py`: setup, explicit reauthentication and options. Duplicate
  controllers and duplicate sessions for an account are rejected before login.
- `coordinator.py`: shared live state, periodic metadata, stale-state checking,
  reconnect backoff, serialized control operations and resource cleanup.
- `models.py`: JSON parsing, sanitized controller fields and numeric handling.
- Entity platforms: sensor, binary sensor, select and button.
- `services.py`: response actions for program readback/segment editing and history.
- `translations/`: English and German setup, options and entity names.

The integration never imports the repository-level diagnostic client. It does
not read `.env`, reuse browser cookies or depend on any local hardware captures.
HA stores account credentials and session cookies in private config-entry storage.
Session loss initiates a reauthentication request without starting a login loop.

Push updates use the observed SockJS XHR transport. Timestamp-based availability
is checked separately so continuous messages with stale device timestamps do not
keep measurements available. Periodic HTTP metadata refresh is scheduled even
while live messages continue. Reconnects do not issue control commands.

Remote control is opt-in. Stop and read-only actions are independent of that
option. Every control operation is serialized, sent once and confirmed with new
controller feedback. Program writes use a fresh device definition and are
confirmed through a newly requested message on the program topic. Ramp encoding
is retained but not editable through the service.

## Diagnostic package

`superwise/` remains a standard-library research CLI with validated `.env`
settings, cookie-session reuse, bounded live capture and private artifact output.
Its synchronous transport is separate from HA's asynchronous client. Both use
allowlisted controller data and distinguish estimated from measured power.

## Data boundaries

Raw cloud responses can include account data and coupling secrets. Neither
runtime client logs or exports raw controller objects. Tests use synthetic
identifiers and programs; real captures remain in ignored `artifacts/`.
Historical curves are action responses rather than large recorder attributes.
Program-original backups returned by editing actions should be retained before
subsequent edits. No automatic program rollback is attempted after an ambiguous
write result because that could overwrite an external change.
