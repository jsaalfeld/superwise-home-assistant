# Superwise Home Assistant

Experimental Python client for bentrup SuperWise. The project provides read-only
cloud diagnostics for development of a Home Assistant integration. It is not yet
an installable HACS integration.

## Features

- Controller status, temperature, setpoint and heating output.
- Program numbers, names and raw segment definitions.
- Firing records and historical sensor curves.
- Live updates via STOMP over SockJS using the HTTP polling transport.
- Optional estimated electrical power based on configured kiln rated power.

Program editing, program selection and firing controls are not exposed by the
client. Program selection has been investigated separately; see the
[protocol notes](docs/findings.md).

## Requirements

Python 3.10 or newer. The runtime uses only the Python standard library.

## Configuration

Copy `.env.example` to `.env` and configure the controller and account:

| Variable | Purpose |
| --- | --- |
| `SUPERWISE_URL` | Server origin; default `https://www.superwise.eu` |
| `SUPERWISE_USERNAME` | Account username |
| `SUPERWISE_PASSWORD` | Account password |
| `SUPERWISE_SERIAL_NUMBER` | Required six-digit controller serial number |
| `SUPERWISE_RATED_POWER_KW` | Optional kiln nameplate power in kW; leave blank to disable estimation |

Environment variables override `.env`. `--serial` overrides the controller for
one invocation. Rated power accepts a decimal point or comma and must be finite
and positive. Settings are validated before connecting. Credentials, sessions
and captured data are excluded from version control.

## Usage

A new login may invalidate another session for the same account. The client
reuses saved sessions and does not automatically log in after session loss.

```bash
# Explicit login and a bounded live capture:
python3 -m superwise --login --listen 20

# Reuse the saved session and fetch historical curves:
python3 -m superwise --history

# Local tests without network access:
python3 -m unittest discover -v
```

`python3 probe.py` remains an alternative entry point. Run either entry point
with `--help` for options. No background service is installed.

The default output is `artifacts/snapshot.json`. Live updates are written to
`artifacts/snapshot.live.jsonl`. `--history` fetches curves for the first listed
firing with a complete time range; an ongoing firing has no end timestamp.
Captured files and the cookie jar under `.local/` are local data.

## Power estimation

`controller.estimated_power_kw` is calculated as
`rated_power_kw × lpValue / 100`. This assumes the reported percentage represents
average heating duty. It is an estimate rather than a measured electrical power
value. Missing, invalid or stale inputs produce `null`; a valid zero remains zero.
Energy integration in kWh is not implemented.

## Limitations

The client uses undocumented web application interfaces. HTML and protocol
changes may break compatibility. Historical result completeness, ramp encoding,
firing-end semantics and independent access from multiple accounts remain
unverified. The current transport is synchronous and must not run directly in
the Home Assistant event loop.

- [Architecture](docs/architecture.md)
- [Protocol notes](docs/findings.md)
- [Validation procedure](docs/test-plan.md)

## License

GNU General Public License v3.0; see [LICENSE](LICENSE).
