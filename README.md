<p align="right">
  <a href="README.md">
    <img src="https://img.shields.io/badge/Language-English-blue?style=for-the-badge">
  </a>
  <a href="README_TH.md">
    <img src="https://img.shields.io/badge/ภาษา-ไทย-green?style=for-the-badge">
  </a>
</p>

# Multi Host Port Checker

A Windows-friendly Tkinter desktop application for monitoring named devices, ICMP Ping latency, and TCP port availability across individual targets or IPv4 ranges.

The Ping and TCP results are independent: a host can respond to Ping while its configured TCP port is offline, or block Ping while its TCP service remains online.

[![Download EXE](https://img.shields.io/badge/Download-MultiPortChecker.exe-brightgreen?style=for-the-badge)](https://github.com/wittayamon/tk-port-checker/releases/latest/download/MultiPortChecker.exe)

## Features

- Add and remove Host/IP + TCP Port targets
- Assign an optional Device Name and edit existing targets in place
- Assign up to 10 Device Groups / Tags and filter persistent targets by group
- Start manual or timed planned-maintenance windows with optional reasons
- One-attempt Ping monitoring with latency, `Timeout`, or `Online` fallback
- Socket-based TCP port checks with color-coded ONLINE/OFFLINE status
- State Change Alerts for TCP DOWN and RECOVERED transitions with downtime display
- Persisted State Change Alerts toggle, enabled by default
- Persistent Event History with DOWN, RECOVERED, MAINTENANCE_STARTED, and MAINTENANCE_ENDED records
- Device/Host and Event Type history filters
- Filter-aware CSV Export and confirmed Clear History controls
- Availability / Uptime Statistics for Today, rolling 7-day, rolling 30-day, and custom date periods
- Raw and Operational Availability, honest Coverage, and planned/unplanned downtime metrics
- Outage Details plus Excel-compatible Summary and Outage CSV exports
- Check Selected and Check All
- Non-overlapping Auto Refresh
- Responsive background checks using a bounded worker pool
- IPv4 Range Scan with progress and cancellation
- Optional display of all scanned IPs
- Duplicate Host/IP + Port rows are updated instead of added again
- Streaming Windows Trace Route with configurable hop and reply-timeout limits
- Save and load JSON host lists
- Auto-load saved hosts and theme configuration
- Dark and Light themes
- Native Windows System Tray with background monitoring controls
- Optional Minimize-to-Tray and persisted Close-to-Tray behavior
- Provider-based notifications for Windows, Generic Webhooks, and Microsoft Teams-compatible endpoints
- Background notification delivery with configurable timeout and retries
- Persistent Notification Delivery History and bounded durable webhook retries
- PyInstaller-compatible icon and resource handling

## Device Names and target data

Device Name is optional and provides a friendly label such as `Demo-PLC`, `NAS-01`, or `Printer-01`. Groups are organizational metadata only: they do not change Host + Port identity, Ping/TCP behavior, or create monitoring sessions. Enter comma-separated values such as `PLC, Critical`; whitespace and empty values are removed, duplicates are removed case-insensitively, each value is limited to 32 characters, and each target is limited to 10 groups. The main **Group** filter is built only from persistent targets; monitoring and **Check All** continue for all persistent targets even while rows are filtered. Report group membership reflects the current config, not a historical snapshot.

Newly saved records support the following format:

```json
{
  "name": "Demo-PLC",
  "host": "192.0.2.10",
  "port": 102,
  "groups": ["PLC", "Critical"],
  "maintenance": {
    "enabled": true,
    "started_at": "2026-09-08T10:00:00+07:00",
    "until": "2026-09-08T11:00:00+07:00",
    "reason": "Planned maintenance"
  }
}
```

Existing records without `name`, `groups`, or `maintenance` continue to load with safe empty/disabled defaults and require no manual migration. Malformed optional metadata is ignored safely.

## Planned Maintenance Mode

Select one persistent target and choose **Start Maintenance**. Available durations are until manually ended, 30 minutes, 1, 2, or 4 hours, and a validated local **Custom End Time**. The optional plain-text reason is limited to 200 characters. **End Maintenance** closes an active window; timed windows expire through one Tk scheduler that continues while the main window is hidden. Active manual/future maintenance is restored after restart, and already-expired state is closed once without fabricating TCP transitions.

Maintenance is independent from TCP state and does not mean ONLINE. Ping and TCP checks continue, the canonical `TcpStateTracker` continues tracking, and real DOWN/RECOVERED evidence remains in Event History. During an active window, Tk state-change dialogs and new Windows/Generic Webhook/Teams operational notifications are suppressed before provider enqueue, so no Notification Delivery History row is created for that transition. Maintenance never cancels or changes delivery/retry rows created before the window.

`MAINTENANCE_STARTED` and `MAINTENANCE_ENDED` audit events persist the historical interval, optional reason, scheduled end, and manual/expired end reason. Ending maintenance while TCP is already OFFLINE does not reset the tracker or fabricate another DOWN; a later real RECOVERED transition is handled normally.

## IPv4 Range Scan

Enter an inclusive Start IP, End IP, and TCP Port, then select **Scan**. For example:

```text
Start IP: 192.168.1.1
End IP:   192.168.1.254
Port:     443
```

The progress label reports values such as `Scanning 37 / 254`. **Cancel Scan** stops submitting new addresses immediately and cancels queued work; network calls already running are allowed to finish safely.

By default, a scan adds or updates only targets where Ping responds or the TCP port is open. Enable **Show all scanned IPs** to include Ping-timeout/TCP-offline results as well. Newly discovered scan rows are runtime results and are not automatically written to the application config on exit. Use **Save List** if you intentionally want to export the visible rows.

Newly discovered scan rows start with an empty Device Name and do not generate State Change Alerts. Manually adding or editing a discovered target promotes it to a persistent monitored target, after which its first regular TCP check establishes the alert baseline.

Ranges must contain valid IPv4 addresses, the end must not be lower than the start, and a scan is limited to 1,024 addresses. Stop Auto Refresh and allow any active check to finish before starting a range scan.

## Trace Route

Select exactly one Host/IP row and choose **Trace Route**. A separate, resizable window runs the trace and displays raw `tracert` output progressively. Both IPv4 addresses and DNS hostnames such as `example.com` are supported.

The default command is:

```powershell
tracert -d -h 15 -w 1000 <host>
```

- `-d` disables DNS hostname lookup for intermediate hops, which avoids lookup delays.
- **Max Hops** defaults to 15 and accepts values from 1 to 255.
- **Timeout** is the wait per reply in milliseconds, defaults to 1000 ms, and accepts values from 1 to 60000 ms.
- **Run Again** clears the output and starts a new trace with the current limits.
- **Stop** terminates the active trace, **Copy** copies all current output, and **Close** safely stops any active trace before closing the window.

Ping, TCP availability, and Trace Route are independent diagnostic signals. A timed-out hop (`* * *`) does not prove that the destination or its TCP service is offline because intermediate routers may ignore ICMP TTL-expired messages. Trace output never changes the table's ONLINE/OFFLINE status.

## Status columns

```text
Device Name | Host / IP | Port | Ping (ms) | Status
```

- Ping values include `7 ms`, `<1 ms`, `Timeout`, or `Online` if Ping succeeds but latency cannot be parsed.
- ONLINE/OFFLINE always represents TCP port availability, not Ping availability.

## State Change Alerts

Enable or disable alerts with **State Change Alerts**. The setting is enabled by default and is stored in `mpc_config.json`; older configs without the setting also default to enabled.

Alerts track only TCP status during **Check Selected**, **Check All**, and **Auto Refresh**:

- The first `UNKNOWN -> ONLINE` or `UNKNOWN -> OFFLINE` result establishes a baseline and does not alert.
- `ONLINE -> OFFLINE` produces one **DEVICE DOWN** warning.
- Repeated OFFLINE results do not produce duplicate alerts.
- `OFFLINE -> ONLINE` produces one **DEVICE RECOVERED** message with the measured downtime.
- If Device Name is empty, Host/IP is used as the primary identifier.
- More than three changes completed in one check cycle are consolidated into one summary dialog.

Ping remains diagnostic information. A Ping `Timeout` does not cause a DOWN alert while the TCP Port remains ONLINE. Runtime IP Range Scan discoveries do not participate in alerts unless they are promoted to persistent monitored targets.

## Windows System Tray

The native Windows notification-area icon starts with the application without any third-party runtime dependency. Startup still shows the normal main window; the application does not start hidden.

The tray menu provides **Open MultiPortChecker**, **Check All**, **Start Auto Refresh**, **Stop Auto Refresh**, **Event History**, **Availability Report**, **Notification Settings**, **Notification History**, and **Exit**. These actions reuse the existing monitoring and Auto Refresh paths, so only one check cycle and one Auto Refresh timer can run. Report, History, and Settings actions restore the application and open or focus the existing window.

- **Hide to Tray** explicitly hides the main window while monitoring continues.
- **Minimize to tray** optionally converts normal minimization into hiding. It is disabled by default.
- **Close button minimizes to tray** is enabled by default. With it enabled, the main window's X hides the application instead of exiting. With it disabled, X fully exits.
- Both tray preferences are stored in `mpc_config.json`; older configs use the safe defaults above.
- Auto Refresh, TCP State Change tracking, downtime calculation, and Event History persistence continue while hidden without creating another monitoring loop.
- Native Tk alert dialogs are deferred while hidden and displayed after the main window is restored, preventing an invisible modal dialog from blocking background monitoring.
- Use the tray menu's **Exit** command for a guaranteed full shutdown of the tray icon, monitoring executors, Trace Route processes, Event History windows, and Tk application.

If the Windows tray icon cannot be initialized, Hide to Tray is disabled and the main-window X exits normally.

## Notification Framework

Choose **Notification Settings** in the main window or System Tray to configure independent delivery providers:

- **Windows Notifications** use the existing native notification-area icon and Windows Shell APIs. No third-party notification package is required.
- **Generic Webhook** sends an HTTP `POST` with a UTF-8 JSON payload suitable for automation.
- **Microsoft Teams** sends an Adaptive Card payload to a user-configured Teams-compatible webhook or Workflow endpoint. Availability depends on the endpoint configured by the user; no legacy connector model is assumed.

All providers are disabled by default, so upgrading does not send external notifications unexpectedly. Windows Notifications are separate from the existing **State Change Alerts** checkbox: users can enable dialogs, Windows notifications, both, or neither. Event History remains active independently of notification settings.

Notifications use the same canonical TCP transitions as alerts and Event History:

- `ONLINE -> OFFLINE` sends one **DOWN** notification.
- `OFFLINE -> ONLINE` sends one **RECOVERED** notification with downtime.
- Initial `UNKNOWN` baselines, repeated states, Ping-only changes, Trace Route results, and transient IP Range Scan discoveries do not notify.
- A promoted persistent scan target may notify only after its normal baseline is established.

External delivery uses one bounded background worker, so HTTP requests never block Tkinter, monitoring, or Event History. Each actual device transition is delivered separately. One provider failure does not stop other providers. HTTP success requires a `2xx` response; failures use a 5-second timeout and two retries by default, delayed by 1 and 3 seconds. Settings accept timeouts from 1–30 seconds and retries from 0–5. Automatic failures update the concise last-result status in Notification Settings without opening repeated modal dialogs.

Each provider has a **Test** button. Test notifications use the fictional `Demo-Device` identity, run in the background, and never change `TcpStateTracker` or Event History. Test results return to the Tk main thread and show a concise success or failure message without revealing an endpoint URL.

Webhook URLs may contain secret tokens. They are masked in Notification Settings with an explicit **Show webhook URLs** control and are never included in history, CSV exports, or delivery diagnostics. URLs are stored locally as sensitive plain text in the ignored `mpc_config.json`; protect access to that file. No custom or misleading encryption is used.

When the application is hidden, Event History, Notification Delivery History, immediate delivery, and enabled delayed retries continue. Existing Tk alert dialogs remain deferred until the main window is restored.

## Notification Delivery History and durable retries

Choose **Notification History** in the main window or System Tray, or **Delivery History** in Notification Settings, to inspect one persistent row for each enabled provider and each real DOWN/RECOVERED event. Disabled providers create no row. Records are newest first and show `QUEUED`, `RETRYING`, `DELIVERED`, or `FAILED`, attempt count, last/next attempt times, and a concise redacted error. Search covers Device and Host; Provider and Status filters are also available.

The initial delivery policy is unchanged: webhook providers make the initial attempt plus the configured immediate retries (two by default), waiting 1 and 3 seconds. Every real attempt increments the same record. Enable **Retry failed webhook deliveries later** to add durable retry cycles after immediate retries are exhausted. It defaults to disabled for existing and new configurations. The bounded schedule is 5, 15, then 60 minutes, with at most three delayed cycles. HTTP 429, HTTP 5xx, timeouts, and temporary network/TLS failures are eligible; typical permanent HTTP 400/401/403/404 responses become `FAILED`. A bounded `Retry-After` value may extend a 429 delay up to 60 minutes.

The backward-compatible config key is `"notification_retry_later_enabled": false`; a missing or malformed value safely defaults to `false`.

Pending retries survive restart in `events.db`, are processed oldest-event-first through the existing bounded worker, and use the provider's current configuration and current endpoint. **Retry Selected** and **Retry All Failed** manually retry terminal failures after configuration is fixed, even when automatic cycles were exhausted. Manual and delayed retries reuse the original event snapshot and timestamp: they do not create a TCP transition or Event History row. A pending DOWN is not cancelled by a later RECOVERED event, so both chronological facts remain independently deliverable.

Delivery History never stores webhook URLs, paths, query tokens, Authorization headers, request headers, response bodies, or credentials. Only provider keys and sanitized categories/summaries such as `HTTP 500` are persisted. Test Notifications are diagnostics and never enter Event History, Delivery History, or the durable queue. Windows notification attempts are recorded as `DELIVERED` when Windows Shell accepts the operation, which does not prove the user saw the balloon; failures are not delayed-retried.

The newest 20,000 terminal delivery rows are retained. `QUEUED` and `RETRYING` rows are never pruned. Confirmed **Clear History** in this window deletes only terminal `DELIVERED`/`FAILED` rows and never changes active deliveries or production Event History.

## Event History

Event History also stores and filters `MAINTENANCE_STARTED` / `MAINTENANCE_ENDED`. Maintenance audit rows include only local reason/end metadata; TCP rows occurring during maintenance remain DOWN/RECOVERED and carry a suppression audit flag in CSV. Groups are not copied into every event; the history Group filter resolves current configured membership.

Choose **Event History** to open a separate, themed window containing persistent TCP state changes, newest first. Baseline results (`UNKNOWN -> ONLINE` and `UNKNOWN -> OFFLINE`) are not logged. Repeated states, Ping-only changes, Trace Route results, and transient IP Range Scan discoveries also do not create history records.

The history table displays:

```text
Date / Time | Device | Host / IP | Port | Event | Ping | Downtime
```

- Search by Device Name or Host/IP.
- Filter Event Type by **All**, **DOWN**, or **RECOVERED**.
- **Export CSV** exports the currently filtered rows with timestamp, transition status, raw downtime seconds, and a formatted downtime value. Files use UTF-8 with BOM for Thai and other Unicode names in Microsoft Excel.
- **Clear History** requires confirmation and deletes only history records; monitored targets, current monitoring state, and settings are unchanged.

Event History uses the standard-library SQLite database `events.db` in the same writable application directory as the local config. The database and table are created automatically when history is first used and are not bundled into the EXE. The newest 10,000 events are retained; older rows are pruned after inserts.

## Availability Report

Choose **Availability Report** in the main window or System Tray to calculate read-only uptime statistics from retained TCP and maintenance Event History. Host + Port remains the identity. The Group filter uses current configured membership; transient scan rows are excluded.

- **Raw Availability** is the unchanged v1.9 TCP result: known uptime / known duration. Maintenance never changes it.
- **Operational Eligible Duration** = known duration minus known duration inside planned maintenance.
- **Operational Availability** = known uptime outside maintenance / operational eligible duration. It displays `-` when eligible duration is zero.
- **Planned Maintenance** is the clipped union of persisted maintenance intervals, including online, offline, and unknown portions.
- **Planned Downtime** is the intersection of known TCP downtime, maintenance intervals, and the report period.
- **Unplanned Downtime** is raw downtime minus planned downtime. Outages are classified `PLANNED`, `UNPLANNED`, or `MIXED`, and Outage Details exposes maintenance overlap.
- **Coverage** remains known duration / requested duration. UNKNOWN time remains unknown during maintenance and never becomes uptime or inflated coverage.

Maintenance intervals crossing either report boundary are clipped, ongoing windows run through report end, and overlapping intervals are merged. Historical maintenance comes from persisted audit events rather than the current config flag. Summary CSV adds groups, raw/operational availability, planned maintenance, and planned/unplanned downtime; Outage CSV adds overlap, unplanned duration, and classification fields. Event CSV exports both maintenance event types and their audit metadata.

Periods have these exact local-time semantics:

- **Today**: local midnight through the current time.
- **7 Days**: the rolling 168 hours ending at the current time.
- **30 Days**: the rolling 720 hours ending at the current time.
- **Custom**: inclusive Start Date and End Date in `YYYY-MM-DD`; completed past dates cover whole local calendar days, while a range ending today is capped at the current time. Invalid dates, an end before the start, and ranges that have not started are rejected.

The latest event before the period establishes the starting state: `DOWN` means OFFLINE and `RECOVERED` means ONLINE. Without earlier evidence, time before the first retained event is UNKNOWN rather than assumed online. Known state continues until another event or the report end. Duplicate `DOWN` while already offline and duplicate `RECOVERED` while already online are ignored by the reporting state machine; `RECOVERED` while unknown establishes online state from that timestamp.

Metrics are calculated as follows:

- **Availability %** = known uptime / known duration × 100. Unknown time is excluded from this denominator.
- **Coverage %** = known duration / requested period duration × 100, making partial evidence visible.
- **Total Downtime**, **Outage Count**, **Longest Outage**, and **Average Outage Duration** use each outage's intersection with the selected period.
- **MTTR** is the average full duration of outages recovered within the selected period. It is `-` when no included outage completed by the report end.

Outages crossing either period boundary are clipped for period downtime. **Outage Details** still shows the actual retained DOWN and RECOVERED timestamps and separates Actual Duration from Period Downtime. A retained DOWN without a later RECOVERED event is marked **ONGOING** and accumulates only through the report end/current time. The Device/Host search filters both the summary and details. Device, Availability, Downtime, and Outages headings support sorting.

**Export Summary CSV** exports the currently filtered summary rows. **Export Outages CSV** exports the currently filtered outage details. Both use UTF-8 with BOM for Excel and Unicode compatibility and contain no notification or webhook data.

Availability is TCP-state based only. Ping-only results, Trace Route, notification delivery state, webhook results, and transient scan rows do not affect it. Reporting runs on a bounded background worker and does not alter Event History, Notification Delivery History, monitoring state, notifications, or retries.

Event History is the sole historical source. Clearing Event History permanently removes the evidence needed to reconstruct reports for the deleted period; there is no hidden backup. Because only the newest 10,000 Event History rows are retained, report depth is limited by that retention and older missing periods appear as unknown coverage rather than uptime.

## Requirements

- Python 3.9 or newer when running from source
- Windows 10/11 is the primary target
- No third-party runtime dependencies

## Run from source

```powershell
python -m venv venv
venv\Scripts\activate
python multi_port_checker.py
```

## Saved data

Host lists support Device Name:

```json
{
  "name": "Demo-PLC",
  "host": "example.com",
  "port": 443
}
```

Older records containing only `host` and `port` remain compatible and load with an empty Device Name. Ping latency, TCP status, outage timestamps, and Trace Route results are runtime values and are not stored in host-list records.

## Build a Windows EXE

Install PyInstaller in the build environment, then use the tracked spec file:

```powershell
pyinstaller --clean --noconfirm MultiPortChecker.spec
```

The executable is created at `dist\MultiPortChecker.exe`. The canonical tracked spec packages `assets/icon_network_transparent.ico` for both the executable and application windows. Python is not required on the target computer.

## Project structure

```text
multi_port_checker.py       Tkinter UI and background task coordination
network_checks.py           Ping, TCP, IPv4 validation, and scan-plan helpers
monitoring_state.py         Host-record compatibility and TCP state tracking
event_history.py            SQLite Event History and CSV export helpers
availability_report.py      UI-independent uptime reconstruction and CSV reports
maintenance.py              Group normalization and planned-maintenance helpers
notification_history.py     SQLite delivery history and durable retry state
windows_tray.py             Native Windows notification-area integration
notification_models.py      Notification events and backward-compatible settings
notification_manager.py     Bounded background delivery and retry coordinator
windows_notifications.py   Native Windows notification provider
webhook_notifications.py   Generic and Teams-compatible webhook providers
assets/
  icon_network_transparent.ico
tests/
  test_ping_helpers.py        Ping/TCP helper tests
  test_range_scan_helpers.py  IPv4 range, duplicate-key, and cancellation tests
  test_trace_route_helpers.py Trace command and input-validation tests
  test_monitoring_state.py    Device-record, transition, and duration tests
  test_event_history.py       Event storage, filtering, retention, and CSV tests
  test_availability_report.py Availability intervals, metrics, filters, and CSV tests
  test_device_groups.py       Group normalization, filtering, persistence, and CSV tests
  test_maintenance_mode.py    Maintenance state, audit, suppression, and report tests
  test_tray_helpers.py        Tray preferences, actions, and lifecycle tests
  test_notification_manager.py Notification settings, transitions, queue, and shutdown tests
  test_notification_history.py Delivery storage, filtering, retention, and recovery tests
  test_notification_retry_queue.py Durable/manual retry and localhost integration tests
  test_webhook_notifications.py Local HTTP delivery and payload tests
  test_windows_notifications.py Native notification formatting/provider tests
MultiPortChecker.spec       PyInstaller build configuration
README.md
README_TH.md
CHANGELOG.md
```

Future documentation screenshots must use sanitized fictional data and belong under `docs/images/`. No documentation screenshot is currently included.

## Tests

```powershell
python -m unittest discover -s tests -v
python -m compileall -q multi_port_checker.py network_checks.py monitoring_state.py maintenance.py event_history.py availability_report.py notification_history.py windows_tray.py notification_models.py notification_manager.py windows_notifications.py webhook_notifications.py tests
```

## Roadmap

- Additional report visualizations and maintenance overview tools
