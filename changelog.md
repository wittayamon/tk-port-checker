# Changelog

All notable changes to this project are documented here.

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
