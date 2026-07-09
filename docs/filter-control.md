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

If the user turns a filter on from the vendor app, button, or smart plug UI, AirMonitor should not immediately fight it.

Preferred behavior:

1. Detect that actual state differs from expected state.
2. Treat it as a temporary manual action or mark state as `external_override`.
3. Surface the condition in logs and Grafana.
4. Do not send an opposite command until the controller has a clear ownership decision.

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
