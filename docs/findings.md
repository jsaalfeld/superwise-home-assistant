# Protocol notes

These interfaces were identified in the authenticated SuperWise web application.
They are not a documented public API and may change.

| Interface | Response / purpose |
| --- | --- |
| `POST /login` | Form fields `username`, `password`; cookie session |
| `GET /dashboard` | HTML containing `controllers.content` |
| `GET /controller/{sn}/view` | Embedded controller, sensors, program names, status and alarms |
| `GET /controller/{sn}/onlinestatus` | Text status such as `PS_RUNNING` or `Offline` |
| `GET /sensor/{sn}/identifier/IN0` | Sensor metadata as JSON |
| `GET /program/{sn}` | Programs with JSON-encoded `payload` definitions |
| `GET /firings` | HTML containing firing records |
| `GET /controller/{sn}/{sensor}/chartdata/{from_ms}/{to_ms}/0` | JSON metadata and timestamp/value pairs, UTC offset 0 |
| SockJS `/ws`, STOMP `/topic/{sn}/data` | Controller state, sensors and optional alarm/event updates |

## Live data

SockJS XHR polling supports STOMP `CONNECT`, `SUBSCRIBE` and `DISCONNECT`.
Messages have been observed both at rest and during an active firing. Updates
were observed approximately every five seconds, with occasional delivery delays;
this is not a guaranteed interval.

| Identifier | Meaning | Unit |
| --- | --- | --- |
| `IN0` | Kiln temperature |°C |
| `SP0` | Temperature setpoint |°C |
| `LP0` | Heating output | % |
| `CJC` | Cold-junction/controller temperature |°C |

`CJC` is not a verified room-temperature measurement. A heating-output percentage
is not a measured kW value. Generic kWh chart support in the web code does not
prove an energy sensor exists for a particular controller.

Controller data includes program number, raw segment number, segment mode,
remaining segment seconds, process status, event code and last-contact timestamp.
Program names can be joined to program numbers from the program list. Raw segment
255 indicates completion rather than an ordinary segment number. Remaining
segment time is not the remaining duration of the entire firing.

## Program selection

The website uses `POST /controller/{sn}/selprog/{number}` with no request body.
Selection and restoration of a program have been confirmed by new live messages
with changed program numbers and increasing sequence numbers. Selection changed
`PS_FINISHED` to `PS_IDLE` without starting a firing. Restoring the program number
did not restore the previous completion status.

Selection during running, paused or scheduled firings has not been validated.
The diagnostic client does not expose this operation. The website has a separate
start action; HTTP success alone is insufficient confirmation of a controller action.

## Execution controls

The following website operations have been tested with fresh controller-state
readback after each request. They are not exposed by the diagnostic client.

| Operation | Request | Confirmed state |
| --- | --- | --- |
| Immediate start | `POST /controller/{sn}/start`, form `delay_date=0` | `PS_RUNNING` |
| Pause | `GET /controller/{sn}/pause` | `PS_HOLDED` |
| Continue | `GET /controller/{sn}/contin` | `PS_RUNNING` |
| Stop | `GET /controller/{sn}/stop` | `PS_STOPPED`, setpoint 0, digital outputs 0 |

These GET endpoints have physical side effects and must not be prefetched or
retried as ordinary read requests. A paused process retained an active digital
output and nonzero heating-output indication; pause is not equivalent to stop.
The first running-state update still contained earlier setpoint/output values,
so a process transition does not imply that every measurement changed atomically.

The original program selection was restored after stopping. Two subsequent
fresh controller states confirmed readiness, zero setpoint and zero digital
outputs. This establishes the reported non-heating state; it does not turn off
the controller's mains supply or independently measure electrical current.
Delayed starts remain unvalidated.

## Program editing and readback

Program-content editing has been tested by changing a single temperature target
by one degree, reading it back from the controller, and restoring the original.
The restored definition and checksum matched the original device readback.
No firing was started, and the final fresh controller state had zero setpoint
and zero digital outputs. The existing program selection was unchanged.

| Operation | Interface |
| --- | --- |
| Submit definition | `POST /program/submit/{sn}` |
| Request definition from controller | `GET /program/{sn}/request/{number}` |
| Read cached definition | `GET /program/{sn}/{number}` |
| Receive requested program | STOMP `/topic/{sn}/prog` |

The website submits serialized program JSON with jQuery's default
`application/x-www-form-urlencoded; charset=UTF-8` content type, rather than
form-encoding individual fields. The controller updates `pcrc`; this derived
field changes with content and returns to its original value on restoration.
Compare the full semantic definition as well as its checksum when validating
round trips. A cached HTTP response alone is not proof of a new device readback.

The generic `/controller/{sn}/responsestatus` endpoint returned HTTP 404 for a
program-read request; the program-topic message is the applicable readback
confirmation. A requested message was delayed once beyond the capture timeout;
a subsequent explicit read request confirmed successful restoration. Do not
resubmit program writes merely because a readback capture times out.

## Programs, history and sessions

Program definitions contain raw ramp, target and dwell fields. Ramp encoding
requires further validation before presenting physical rates or predicted times.
Historical responses include temperature, setpoint and heating-output curves.
Firing-list pagination and completeness are unverified.

`endAt - startAt` describes the returned record interval. The relationship between
program completion, recording completion and cooling must be established before
labeling this interval as firing duration. An ongoing record may have
`recording=true` and `endAt=null`.

New logins may invalidate existing sessions for the same account. Independent
sessions for different accounts sharing a controller have not been validated.
The client requires explicit login and stops when its session is lost.
