# Changelog

All notable changes to this project are documented here.

## v1.10.0 - 2026-09-08

### Added

- Device Groups / Tags with normalized comma-separated editing, persistent target-list display, and current-config group filtering.
- Planned Maintenance Mode with manual, 30-minute, 1-hour, 2-hour, 4-hour, and custom local end-time windows.
- Restart-safe maintenance state, automatic expiry, and persistent `MAINTENANCE_STARTED` / `MAINTENANCE_ENDED` audit events.
- Maintenance-aware Availability reporting with Raw and Operational Availability, planned maintenance, planned/unplanned downtime, and planned/unplanned/mixed outage classification.
- Group-aware Availability filtering plus expanded Summary, Outage, and Event History CSV fields.

### Improved

- Operational Availability excludes known monitored time inside persisted planned-maintenance intervals while Raw Availability remains identical to v1.9 behavior.
- TCP state tracking and DOWN/RECOVERED Event History evidence continue during maintenance, while operational Tk, Windows, Generic Webhook, and Teams notifications are suppressed before enqueue.
- Timed maintenance expiry continues while hidden in the System Tray and restores safely across restart without duplicate end events or fabricated TCP transitions.
- Existing durable notification retries remain independent and are never retroactively cancelled by maintenance.
- Old target configs and Event History databases migrate automatically with safe defaults for missing or malformed optional metadata.

## v1.9.0 - 2026-09-07

### Added

- Availability / Uptime Report derived from retained TCP Event History.
- Today, rolling 7-day, rolling 30-day, and validated custom-date reporting periods.
- Availability and Coverage percentages, known/unknown duration, total downtime, outage count, longest outage, average outage duration, and MTTR.
- Themed Outage Details view with actual event timestamps, clipped period downtime, and RECOVERED/ONGOING status.
- Filtered UTF-8 BOM Summary and Outage Detail CSV exports.
- Main-window and native System Tray entry points with reusable/focused report windows.
- Host + Port report identity with current/most-recent Device Name display and explicit zero-coverage rows for configured targets without evidence.

### Improved

- Unknown monitoring periods are excluded from the Availability denominator and exposed through Coverage rather than silently counted as uptime.
- Outages crossing report boundaries are clipped using interval intersection while preserving actual retained timestamps.
- Unresolved DOWN events accumulate through the report end and are reported as ONGOING.
- Duplicate or malformed historical transition sequences are normalized defensively by a UI-independent state machine.
- Report querying and calculation run on a bounded background worker and remain independent from monitoring, Event History mutation, and Notification Delivery History.
- Persistent TCP Event History remains the sole report source; Ping-only and transient range-scan results remain excluded.

## v1.8.0 - 2026-09-06

### Added

- Persistent Notification Delivery History with explicit `QUEUED`, `RETRYING`, `DELIVERED`, and `FAILED` states in a separate `notification_deliveries` table within `events.db`.
- Bounded durable retry queue for Generic Webhook and Teams-compatible providers.
- Optional automatic retry-later scheduling at 5, 15, and 60 minutes, bounded to three delayed cycles.
- Manual **Retry Selected** and **Retry All Failed** actions.
- Device/Host search plus Provider and Status delivery-history filters.
- Startup recovery of pending and interrupted webhook deliveries.
- Main-window, Notification Settings, and System Tray access to Notification History.

### Improved

- Notification auditability with attempt counts and original event timestamps.
- Preserved the existing initial delivery plus immediate retries before durable retry-later scheduling is considered.
- Safe structured failure categories and redacted persisted diagnostics.
- Retry state persistence across application restarts and hidden/System Tray operation.
- Retried deliveries resolve the current enabled provider configuration without storing endpoint URLs or credentials in Delivery History.
- Oldest-event-first due processing and duplicate in-process job protection.
- Bounded retention of the newest 20,000 terminal delivery records while preserving active rows.
- Canonical shutdown now stops both delivery and retry-scheduler workers while leaving recoverable durable state.
- Native tray ctypes cleanup now preserves the original startup error on 64-bit Windows handles.

## v1.7.0 - 2026-09-05

### Added

- Provider-based Notification Framework driven by canonical TCP transitions.
- Shared UI-independent `NotificationEvent` model for DOWN / RECOVERED delivery.
- Native Windows DOWN / RECOVERED notifications through the existing System Tray icon.
- Generic HTTP JSON webhook and Microsoft Teams-compatible Adaptive Card providers.
- Themed Notification Settings window with provider enable/disable controls and a System Tray entry point.
- Background Test Notification actions with concise delivery results.
- Configurable HTTP timeout and retry policy.

### Improved

- Continued external notification delivery while hidden in the System Tray.
- Isolated provider failures from monitoring, Event History, and other providers.
- Masked locally stored webhook endpoints and redacted them from diagnostics.
- Integrated the bounded notification worker into canonical clean shutdown.
- Preserved v1.6 configuration compatibility with safe disabled-by-default provider settings.

## v1.6.0 - 2026-09-04

### Added

- Native Windows System Tray support using standard-library `ctypes` and Windows Shell APIs without third-party runtime dependencies.
- Tray menu actions for Open MultiPortChecker, Check All, Start Auto Refresh, Stop Auto Refresh, Event History, and Exit.
- Hide to Tray plus persisted optional Minimize-to-Tray and default-enabled Close-to-Tray preferences.
- Background monitoring while the main window is hidden.

### Improved

- Unified real-exit shutdown with idempotent tray and process cleanup.
- Continued DOWN / RECOVERED tracking, downtime calculation, and Event History persistence while hidden.
- Deferred Tk alert dialogs until the hidden main window is restored.

## v1.5.0 - 2026-09-04

### Added

- Persistent Event History backed by SQLite
- Newest-first Event History window
- DOWN / RECOVERED event logging
- Device/Host search and DOWN / RECOVERED event filtering
- Filter-aware CSV Export with UTF-8/Unicode support
- Clear History
- Automatic retention of the newest 10,000 events

### Improved

- Public repository examples sanitized
- Generic fictional example naming
- Public-repository safety rules added to AGENTS.md
- Excluded initial baseline states, repeated states, Ping-only changes, and transient IP Range Scan results from Event History.
- Reorganized tests and application assets.
- Standardized the `CHANGELOG.md` filename.
- Removed the obsolete unsanitized screenshot.
- Tracked the canonical PyInstaller build configuration.

## v1.4.0 - 2026-09-03

- Added an optional Device Name column and input for monitored targets.
- Added Edit Selected support for Device Name, Host/IP, and Port.
- Extended saved host records with a backward-compatible optional `name` field.
- Added TCP-only State Change Alerts for DOWN and RECOVERED transitions.
- Added initial-baseline suppression, duplicate-alert prevention, and downtime display.
- Added a persisted State Change Alerts toggle that defaults to enabled for old configs.
- Excluded transient IP Range Scan discoveries from alerts until they are promoted.
- Added consolidated alert summaries when more than three targets change in one cycle.
- Added focused tests for host-record compatibility, TCP transitions, and durations.

## v1.3.0 - 2026-09-03

- Added a Trace Route action for a selected Host/IP using Windows `tracert -d`.
- Added streaming raw trace output in a responsive, themed Toplevel window.
- Added configurable Max Hops and per-reply Timeout values with validation.
- Added Run Again, Stop, Copy, and safe trace-window/process cleanup behavior.
- Applied the application icon consistently to the main and Trace Route windows.
- Kept Trace Route independent from Ping and TCP ONLINE/OFFLINE results.
- Added focused tests for tracert command construction and input validation.

## v1.2.0 - 2026-09-02

- Added inclusive IPv4 Range Scan controls for Start IP, End IP, and TCP Port.
- Added bounded concurrent scanning with progress and cancellation.
- Added optional display of Ping-timeout/TCP-offline scan results.
- Added duplicate target detection so scans update matching Host/IP + Port rows.
- Kept newly discovered scan rows out of automatic config persistence.
- Added IPv4 range validation with a maximum of 1,024 addresses.
- Added focused tests for validation, duplicate keys, scan batching, and cancellation.

## v1.1.0 — Ping Monitoring

- Added locale-tolerant Ping latency monitoring.
- Kept Ping and TCP availability independent.
- Moved network checks to a bounded background worker pool.
- Prevented overlapping Auto Refresh cycles.

## v1.0.0 — Initial Release

- Added multi-host port checker.
- Added auto refresh interval.
- Added icon support.
- Added EXE build system.
