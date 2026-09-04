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
- One-attempt Ping monitoring with latency, `Timeout`, or `Online` fallback
- Socket-based TCP port checks with color-coded ONLINE/OFFLINE status
- State Change Alerts for TCP DOWN and RECOVERED transitions with downtime display
- Persisted State Change Alerts toggle, enabled by default
- Persistent Event History with newest-first DOWN and RECOVERED records
- Device/Host and Event Type history filters
- Filter-aware CSV Export and confirmed Clear History controls
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
- PyInstaller-compatible icon and resource handling

## Device Names and target data

Device Name is optional and provides a friendly label such as `Demo-PLC`, `NAS-01`, or `Printer-01`. Select one row and choose **Edit Selected** to populate the Device Name, Host/IP, and Port fields; choose **Apply** to update the row without deleting and re-adding it.

Newly saved records support the following format:

```json
{
  "name": "Demo-PLC",
  "host": "192.168.1.100",
  "port": 102
}
```

Existing records without `name` continue to load with an empty Device Name and require no manual migration.

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

## Event History

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
pyinstaller --noconfirm MultiPortChecker.spec
```

The executable is created at `dist\MultiPortChecker.exe`. Python is not required on the target computer.

## Project structure

```text
multi_port_checker.py       Tkinter UI and background task coordination
network_checks.py           Ping, TCP, IPv4 validation, and scan-plan helpers
monitoring_state.py         Host-record compatibility and TCP state tracking
event_history.py            SQLite Event History and CSV export helpers
test_ping_helpers.py        Ping/TCP helper tests
test_range_scan_helpers.py  IPv4 range, duplicate-key, and cancellation tests
test_trace_route_helpers.py Trace command and input-validation tests
test_monitoring_state.py    Device-record, transition, and duration tests
test_event_history.py       Event storage, filtering, retention, and CSV tests
MultiPortChecker.spec       PyInstaller build configuration
icon_network_transparent.ico
README.md
README_TH.md
changelog.md
```

## Tests

```powershell
python -m unittest -v
python -m py_compile multi_port_checker.py network_checks.py monitoring_state.py event_history.py test_ping_helpers.py test_range_scan_helpers.py test_trace_route_helpers.py test_monitoring_state.py test_event_history.py
```

## Roadmap

- System tray support
- Optional Event History date-range filtering
