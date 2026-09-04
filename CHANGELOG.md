# Changelog

All notable changes to this project are documented here.

## Unreleased — recommended v1.6.0

### Added

- Native Windows System Tray support without third-party runtime dependencies.
- Tray menu actions for Open, Check All, Auto Refresh, Event History, and Exit.
- Persisted Minimize-to-Tray and Close-to-Tray preferences.
- Background monitoring while the main window is hidden.

### Improved

- Unified real-exit shutdown and idempotent tray cleanup.
- Continued State Change and Event History processing while hidden.
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
