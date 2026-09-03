# Multi Host Port Checker

A Windows-friendly Tkinter desktop application for monitoring ICMP Ping latency and TCP port availability across individual targets or IPv4 ranges.

The Ping and TCP results are independent: a host can respond to Ping while its configured TCP port is offline, or block Ping while its TCP service remains online.

[![Download EXE](https://img.shields.io/badge/Download-MultiPortChecker.exe-brightgreen?style=for-the-badge)](https://github.com/wittayamon/tk-port-checker/releases/latest/download/MultiPortChecker.exe)

## Features

- Add and remove Host/IP + TCP Port targets
- One-attempt Ping monitoring with latency, `Timeout`, or `Online` fallback
- Socket-based TCP port checks with color-coded ONLINE/OFFLINE status
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

## IPv4 Range Scan

Enter an inclusive Start IP, End IP, and TCP Port, then select **Scan**. For example:

```text
Start IP: 192.168.1.1
End IP:   192.168.1.254
Port:     443
```

The progress label reports values such as `Scanning 37 / 254`. **Cancel Scan** stops submitting new addresses immediately and cancels queued work; network calls already running are allowed to finish safely.

By default, a scan adds or updates only targets where Ping responds or the TCP port is open. Enable **Show all scanned IPs** to include Ping-timeout/TCP-offline results as well. Newly discovered scan rows are runtime results and are not automatically written to the application config on exit. Use **Save List** if you intentionally want to export the visible rows.

Ranges must contain valid IPv4 addresses, the end must not be lower than the start, and a scan is limited to 1,024 addresses. Stop Auto Refresh and allow any active check to finish before starting a range scan.

## Trace Route

Select exactly one Host/IP row and choose **Trace Route**. A separate, resizable window runs the trace and displays raw `tracert` output progressively. Both IPv4 addresses and DNS hostnames such as `google.com` are supported.

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
Host / IP | Port | Ping (ms) | Status
```

- Ping values include `7 ms`, `<1 ms`, `Timeout`, or `Online` if Ping succeeds but latency cannot be parsed.
- ONLINE/OFFLINE always represents TCP port availability, not Ping availability.

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

Host lists remain compatible with the existing format:

```json
{
  "host": "google.com",
  "port": 443
}
```

Ping latency and TCP status are runtime values and are not required in saved files.

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
test_ping_helpers.py        Ping/TCP helper tests
test_range_scan_helpers.py  IPv4 range, duplicate-key, and cancellation tests
test_trace_route_helpers.py Trace command and input-validation tests
MultiPortChecker.spec       PyInstaller build configuration
icon_network_transparent.ico
README.md
changelog.md
```

## Tests

```powershell
python -m unittest -v
python -m py_compile multi_port_checker.py network_checks.py test_ping_helpers.py test_range_scan_helpers.py test_trace_route_helpers.py
```

## Roadmap

- System tray support
- Optional notifications when a monitored service changes state
- External status logging
