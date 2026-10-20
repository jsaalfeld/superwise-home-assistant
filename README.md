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

### Manual installation

1. Copy `custom_components/superwise` into `/config/custom_components/superwise`.
   The final path must be `/config/custom_components/superwise/manifest.json`.
2. Restart Home Assistant.
3. Open **Settings → Devices & services → Add integration → Superwise**.
4. Enter the server URL, credentials, six-digit controller serial and optional
   rated power in kW. Use 0 to disable the power estimate.

A distribution ZIP contains the `custom_components/superwise/` directory and can
be extracted into the Home Assistant configuration directory. Do not copy `.env`,
`.local`, captured data or the standalone diagnostic client into Home Assistant.

### HACS custom repository

Add
`https://github.com/jsaalfeld/superwise-home-assistant` as a HACS custom repository
of type **Integration**, download **Superwise**, restart HA and follow the setup
steps above. The integration is not listed in the default HACS catalog.

## Account sessions

Creating a session may invalidate another login for the same account. Setup and
explicit reauthentication create a session. HA restarts, reconnects and option
changes reuse the stored session; they never silently log in. If a browser or
another client replaces that session, HA requests reauthentication and stops
using it until the request is completed.

One configuration per account is allowed to avoid competing sessions inside HA.
Independent access using separate accounts for the same kiln is not yet verified.
Credentials and session cookies are stored in HA's private config-entry storage;
include that storage in your normal secret and backup handling.

## Entities and options

The integration creates a device with:

- Kiln temperature, setpoint, heating-output percentage and controller temperature.
- Estimated electrical power when rated power is configured.
- Process status, program name, segment and segment remaining time.
- Last contact, latest record start and last completed recording duration.
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
old. Live STOMP updates are combined with periodic HTTP checks and metadata
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

See [protocol notes](docs/findings.md), [architecture](docs/architecture.md) and
[validation procedure](docs/test-plan.md).

## Development

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
