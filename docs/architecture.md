# Architecture

The project separates settings, data normalization and cloud communication from
the command line interface. It currently provides a synchronous diagnostic client.

```text
superwise/
  settings.py     Environment configuration and validation
  models.py       Embedded JSON parsing and measurement normalization
  client.py       Cookie session, read-only HTTP access and SockJS/STOMP
  cli.py          Diagnostic command line interface
  __main__.py     Module entry point
probe.py          Compatibility entry point
tests/           Offline tests using synthetic data
```

`Settings` holds account credentials, controller identity and optional rated
power. Credentials are omitted from its representation. Configuration is loaded
from `.env`, with process environment variables taking precedence. The CLI
requires a controller serial number before connecting.

`Client` reuses a cookie session. Authentication is explicit, and session loss
never triggers an automatic login loop. HTTP POST is used for authentication and
SockJS connection messages; the client exposes no kiln-control operations.

`models.py` parses embedded page JSON without executing JavaScript. Controller
exports use an allowlist to exclude account fields and coupling secrets. Invalid
numeric values become `null`. Freshness is derived from the controller timestamp;
data at least 60 seconds old is considered stale.

Optional power estimation uses rated power and a fresh heating-output percentage
in the range 0–100. Neither percent output nor the estimate is an electrical meter.

## Home Assistant integration boundary

The client is not a Home Assistant integration. A future adapter needs asynchronous
communication, shared state updates, entity availability and explicit handling of
session expiry. Large historical curves should be kept outside entity attributes
and the state recorder. Estimated power must remain distinguishable from measured
power. Energy calculations need defined behavior for missing intervals.

## Local data

`.env`, `.local/` and `artifacts/` are excluded from Git. Raw server responses can
contain account data and coupling secrets and must not be published as fixtures.
Automated tests use synthetic data. Personal development instructions belong in
local, ignored files rather than public project documentation.
