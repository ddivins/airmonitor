# Filter control and manual override model

AirMonitor filter automation must never fight the user.

Automation should make recommendations. A filter controller decides the effective device state after considering manual override mode, policy recommendations, safety rules, and observed device state.

## Modes

Each controllable filter has one of three modes:

```text
auto
on
off
```

### auto

Automation controls the filter.

Examples:

```text
Printing ABS/ASA      -> on
Printing PLA/PETG     -> usually off or Bento-only, depending policy
VOC above threshold   -> on
Cooldown complete     -> off
```

### on

Manual override forces the filter on.

Automation must not turn the filter off while mode is `on`.

This is used when the user wants to clean the room, run the filter for odor, or manually ventilate before/after a print.

### off

Manual override forces the filter off.

Automation must not turn the filter on while mode is `off`.

If VOC/PM reaches a safety threshold, AirMonitor should log and surface a warning, but still not silently override the user's explicit off state unless an explicit emergency policy is later added.

## Effective state

The controller should track four separate values:

```text
manual_mode: auto | on | off
automation_request: on | off
actual_state: on | off | unknown
effective_state: on | off
```

Resolution:

```text
manual_mode=on   -> effective_state=on
manual_mode=off  -> effective_state=off
manual_mode=auto -> effective_state=automation_request
```

## CLI

Desired commands:

```bash
airmonitor filter status
airmonitor filter all status
airmonitor filter bento status
airmonitor filter levoit status

airmonitor filter bento auto
airmonitor filter bento on
airmonitor filter bento off

airmonitor filter levoit auto
airmonitor filter levoit on
airmonitor filter levoit off

airmonitor filter all auto
airmonitor filter all on
airmonitor filter all off
```

## Grafana

The dashboard should show, for each filter:

```text
Name
Actual state
Manual mode
Automation request
Effective state
Reason
Last command time
```

Examples:

```text
Bento
Actual: ON
Mode: MANUAL ON
Reason: User override
```

```text
Levoit
Actual: ON
Mode: AUTO
Reason: Printing ABS
```

## Out-of-band changes

The Levoit and Bento services compare observed device state with the state last
commanded by AirMonitor. An external ON change (VeSync, Kasa, or a physical
button) latches that filter in manual `on` mode. An external OFF change returns
the filter to `auto` and immediately reconciles it with the current automation
request. This means an active print can turn a manually stopped filter back on.

Levoit detects changes during its normal device poll. Bento polls its local Kasa
outlet every `OUTLET_POLL_SECONDS` (15 seconds by default). The resulting manual
mode and reason are persisted and shown on the status page.

## Levoit's manual override wake signal

Bento reacts to its own manual overrides essentially immediately -- it's fully
event-driven off local MQTT, no cloud API involved. Levoit is different: it's
controlled through VeSync's cloud API on a fixed poll cadence
(`LEVOIT_POLL_INTERVAL_SECONDS`, 120s by default, deliberately not shortened --
polling VeSync more often gets the account rate-limited), so a manual on/auto/off
click from the status page used to sit unapplied for up to that long.

`airmonitor-status.service` and `airmonitor-levoit.service` both run as the
`automation` user, so after persisting a manual override for Levoit specifically,
the status page sends `airmonitor-levoit.service`'s process `SIGUSR1`
(`wake_levoit_service()` in `status_web.py`) -- no elevated privilege needed,
since sending a signal only requires the sender and target share a user (or the
sender be root). The service's main loop waits on a `threading.Event` instead of
a plain sleep (`sleep_until_next_poll()`), and `SIGUSR1` sets that event, waking
it immediately to apply the change. `SIGTERM`/`SIGINT` (systemd stop requests)
set the same event, so shutdown responsiveness is unaffected.

This only speeds up a deliberate, one-off button click -- the poll interval
itself, and therefore VeSync's request volume in steady state, is unchanged. If
the wake signal fails for any reason (service not running, `systemctl show`
unavailable, etc.) it's swallowed silently: the manual override is already
persisted by that point, so the change still applies on the next normal poll
regardless.

## Persistence

Manual override state should survive service restarts.

Possible storage:

```text
/var/lib/airmonitor/airmonitor.sqlite3
```

Suggested table:

```sql
CREATE TABLE IF NOT EXISTS filter_control_state (
    filter_id TEXT PRIMARY KEY,
    manual_mode TEXT NOT NULL DEFAULT 'auto',
    automation_request TEXT,
    actual_state TEXT,
    effective_state TEXT,
    reason TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
```

## Design rule

Automation recommends. The controller commands. Manual override wins.
