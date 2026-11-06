# Superwise for Home Assistant

A Home Assistant integration for bentrup SuperWise kiln controllers. Read live
values, select programs, control a firing, edit program segments and retrieve
firing history. It connects through the same cloud interfaces as the SuperWise
website. These interfaces are undocumented and may change.

**Experimental:** tested with Home Assistant 2026.10.2 and a TC75 controller.
Setup, live values, read-only actions and options reload have been checked in HA.
Start, pause, continue and stop have been tested directly against the controller,
but still need a supervised test through the installed integration.

## Installation

Requires Home Assistant 2026.10 or newer.

### Marketplace (Home Assistant 2026.11 or newer)

1. Open **Settings → Marketplace → Add from link** and enter
   `https://github.com/jsaalfeld/superwise-home-assistant`.
2. Connect your GitHub account if prompted. If asked for the content type,
   select **Integration**.
3. Open **Superwise** and select **Install**. Restart Home Assistant if prompted,
   then follow the integration setup below.

The Marketplace continues to use `hacs.json`; no separate Marketplace manifest
is needed. Existing HACS installations and custom repositories migrate
automatically when upgrading to Home Assistant 2026.11. The button below also
continues to work in the Marketplace. See the
[official Marketplace documentation](https://www.home-assistant.io/integrations/marketplace/).

Compatibility check: all nine integration modules import successfully with Home
Assistant 2026.11.0. A complete test run on 2026.11 is not yet verified: the pinned
`pytest-homeassistant-custom-component` package targets HA 2026.10.2 and fails
during test initialization with 2026.11. Marketplace installation itself has not
yet been tested end to end.

### HACS (Home Assistant 2026.10)

[![Open Superwise in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jsaalfeld&repository=superwise-home-assistant&category=integration)

1. Click the button above, or open **HACS → ⋮ → Custom repositories** and add
   `https://github.com/jsaalfeld/superwise-home-assistant` as **Integration**.
2. Download **Superwise** and restart Home Assistant.

### Integration setup

1. Open **Settings → Devices & services → Add integration → Superwise**, or use:

   [![Set up Superwise](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=superwise)

2. Enter the server URL, credentials and optional rated power in kW. Use 0 to
   disable the power estimate. The integration finds the controllers in your
   account. If there is more than one, choose the kiln to use.

The repository button opens HACS or the Marketplace in your Home Assistant
instance. Confirm adding it and install the integration there.

### Manual installation

1. Copy `custom_components/superwise` into `/config/custom_components/superwise`.
   The final path must be `/config/custom_components/superwise/manifest.json`.
2. Restart Home Assistant and follow the setup steps above.

A distribution ZIP contains the `custom_components/superwise/` directory and can
be extracted into the Home Assistant configuration directory. Do not copy `.env`,
`.local`, captured data or the standalone diagnostic client into Home Assistant.

## Account sessions

Creating a session may invalidate another login for the same account. HA restarts,
reconnects and option changes reuse the stored session first. When that session
expires or is replaced, the integration automatically signs in with the stored
password and saves the renewed session. Login attempts are serialized and limited
to one per minute. Rejected credentials require explicit reauthentication. Confirm
that request with the stored password or enter a replacement password. Controller
commands are never automatically replayed after authentication failure.

One kiln per account can be configured to avoid competing sessions inside HA.
Existing configurations keep their selected controller and entity IDs.
Independent access using separate accounts for the same kiln is not yet verified.
Credentials and session cookies are stored in HA's private config-entry storage;
include that storage in your normal secret and backup handling.

## Entities and options

The integration creates a device with:

- Kiln temperature, setpoint, heating-output percentage and controller temperature.
- Estimated electrical power when rated power is configured.
- Process status, program name, segment and segment remaining time.
- Last contact, latest record start and last completed recording duration.
- Controller error code as a diagnostic sensor (0 means no reported error).
- Connection and program-active binary sensors.
- Program selection plus Start, Stop, Pause and Continue buttons.

In **Configure**, set rated power and enable remote control if desired. Remote
control is disabled initially; readout and history work without it. Stop remains
available independently of this option. No command is executed during setup,
reload or reconnect. Program selection does not start a firing.

**Pause is not an off command:** the controller may keep heating while paused.
Stop waits for a fresh idle/stopped state, zero setpoint and zero reported digital
outputs. This is controller feedback, not independent current measurement, and
does not disconnect the mains supply. An uncertain command result is reported
without automatically repeating the command.

Values become unavailable when the controller timestamp is at least 60 seconds
old. Live STOMP updates are combined with periodic JSON status checks and metadata
refreshes. Missing heating output is not treated as zero.

## Program and history actions

Under **Developer tools → Actions**, use the following response actions. Select
the integration entry in each action. Scripts must set a `response_variable`.

| Action | Purpose |
| --- | --- |
| `superwise.read_program` | Request a program directly from the controller |
| `superwise.update_program` | Change a segment temperature and/or dwell time and verify device readback |
| `superwise.list_firings` | Return available firing IDs, program numbers and record timestamps |
| `superwise.get_firing_history` | Return one record and its four sensor curves |

Program editing requires remote control enabled and a fresh idle controller with
outputs and setpoint off. Segment numbers start at 1. Temperature is a whole
number in °C. Dwell editing accepts whole minutes for minute-resolution programs;
HOLD and ramp editing are not supported. Controller limits are checked before
submitting. The response includes `previous_program` and the verified new program.
A write or readback failure is not automatically retried or rolled back: inspect
the controller state before another write. Program edits never start a firing.

Example script action:

```yaml
action: superwise.update_program
data:
  config_entry_id: REPLACE_WITH_ENTRY_ID
  program: 1
  segment: 1
  temperature: 200
response_variable: program_result
```

Historical curves are returned as action responses, not stored in entity
attributes or the state recorder. The firing list may be incomplete. Record
start/end semantics can include recording beyond program completion; recording
duration may differ from heating or firing duration.

## Estimated power

Estimated power is `rated_power_kw × heating_output / 100`. This assumes the
percentage represents average heater duty and is **not measured electrical
power**. The estimate is unavailable when its inputs are invalid, missing or
stale. No energy counter is included; an energy estimate needs time integration
and explicit treatment of missing intervals.

## Limitations

- Unofficial web interfaces can change without notice.
- Hardware behavior was explored with TC75; other controllers are unverified.
- Delayed start, alarm management, ramp editing and complete website/account
  administration are not implemented.
- Automated tests use synthetic data and do not connect to a real controller.

## Manufacturer protocol reference

bentrup documents serial controller communication in
[Application Note AN0902: Communication Options on bentrup Controllers](https://bentrup.de/wp-pdf/downloads/an/an0902.pdf).
Option B describes a proprietary binary protocol over RS232/RS485; option A uses
a licensed Windows DDE server. This is separate from the SuperWise cloud interface.
Compatibility, connector pinout and interface availability must be confirmed for
the specific controller before implementing a local connection. Serial support
is not implemented in this integration.

A local reference copy may be kept as `an0902.pdf` in the repository root. It is
Git-ignored and must not be committed or included in release assets.

See [protocol notes](docs/findings.md), [architecture](docs/architecture.md) and
[validation procedure](docs/test-plan.md).

## Development

GitHub Actions run the tests, hassfest and HACS validation. Validation also runs
daily. Dependabot checks Python dependencies and GitHub Actions weekly and opens
update pull requests.

The standalone diagnostic CLI is available as `python3 -m superwise`.
Only that CLI reads `.env`; the HA integration uses its setup/options dialogs.
The `.env.example` template documents the diagnostic settings. Explicit CLI login
may displace an existing account session, just like integration setup.

```bash
# Standard-library diagnostic tests:
python3 -m unittest discover -v

# Home Assistant tests in a container without network access:
podman build -f Containerfile.test -t superwise-ha-test .
podman run --rm --network none \
  -v "$PWD/custom_components:/work/custom_components:ro,Z" \
  -v "$PWD/tests_ha:/work/tests_ha:ro,Z" \
  -v "$PWD/tests:/work/tests:ro,Z" \
  -v "$PWD/superwise:/work/superwise:ro,Z" \
  -v "$PWD/probe.py:/work/probe.py:ro,Z" \
  -v "$PWD/pytest.ini:/work/pytest.ini:ro,Z" \
  superwise-ha-test
```

Tests use synthetic data. Credentials, sessions and hardware captures are
excluded from version control.

## License

GNU General Public License v3.0; see [LICENSE](LICENSE).

### Cooling time estimates

Two timestamp sensors, **Estimated 200 °C time** and **Estimated 100 °C time**,
show when the kiln is expected to cool to these temperatures. Home Assistant
shows the timestamps in the user's local time zone.

The estimate fits an exponential curve to up to two hours of recent temperature
measurements, assuming a 15 °C ambient temperature. It needs at least 30 minutes
of consistent cooling and rounds the predicted time to five minutes. This models
the slowing cooling rate rather than extending a constant °C/hour decline.
When available, Recorder history seeds the model after an integration reload or
restart; Recorder is optional. No additional cloud history requests are made.

Estimates are unavailable while a program is active, when heating is indicated,
when telemetry is stale or interrupted, when the cooling trend is unsuitable,
or once the respective target has already been reached. They describe measured
kiln temperature, **not whether ware is safe to handle**. Loading, room temperature,
and opening the kiln can change the actual cooling time; forecasts far into the
future are approximate and are continuously revised.
