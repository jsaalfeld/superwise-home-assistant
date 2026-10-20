# Testing

Automated tests use synthetic data and must run without cloud access:

```bash
python3 -m unittest discover -v
```

## Hardware validation

Use a dedicated test window with an operator able to verify controller behavior.
Save the original program configuration before testing program writes. Validate
control actions only when interruption of a firing is acceptable.

| Area | Verification |
| --- | --- |
| Sessions | Establish whether separate accounts can access one controller independently without replacing its existing association |
| Readout | Compare program, temperature and timestamp against the controller display |
| Selection | Select and restore a program; confirm both changes through new controller messages and the physical display |
| Program editing | Back up a test program, transfer changes, read them back and restore the original |
| Start | Confirm actual execution through the controller display and a fresh process-state update |
| Monitoring | Observe temperature, setpoint, heating output and multiple segment transitions |
| Connection loss | Disconnect only the diagnostic client; verify stale-state handling and absence of automatic login or repeated control commands |
| Pause/resume/stop | Verify each supported operation separately against the controller state |
| Completion | Distinguish program completion, recording completion and cooling using timestamps and display state |
| History | Retrieve the completed record and compare curves and duration semantics |
| Cleanup | Verify restored configuration and terminate diagnostic connections |

Several of these operations are not implemented in the current diagnostic client.
A successful empty HTTP response does not establish that the controller executed
an action. Verify the resulting state before sending another action. Do not
retry ambiguous control requests blindly.

## Test notes

Record expected and actual behavior, relevant controller states, sequence
numbers and timestamps. Keep credentials, coupling secrets, personal device
identifiers and raw account responses out of shared reports and fixtures.
Private captures belong under the ignored `artifacts/` directory; published
fixtures must use synthetic data.

## Integration verification

The `tests_ha/` suite runs against Home Assistant in a rootless Podman container
with networking disabled. It verifies setup, duplicate rejection, stored-session
reuse, explicit reauthentication, options, entity registration/unload, stale
availability, command gating, single-send behavior, program readback comparisons
and response actions. No actual kiln commands are sent by automated tests.

When testing on hardware, install the integration and check live values first,
then enable remote control for a supervised control test. Protocol-level hardware
tests do not replace testing the complete installed HA integration. Verify unload,
restart and replacement of the session from the website without automatic login.
