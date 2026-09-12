# AGENTS.md

## Project Overview

This repository contains **Multi Host Port Checker**, a Windows desktop network monitoring tool written in Python with Tkinter.

Main capabilities currently include:

- Add and remove multiple Host/IP + TCP Port targets
- Optional Device Name and in-place target editing
- Check TCP port availability
- Ping monitoring with latency display
- Ping and TCP status are intentionally independent
- Check Selected
- Check All
- Auto Refresh
- Background network checks so the Tkinter UI remains responsive
- IPv4 Range Scan with progress and cancellation
- Trace Route with streaming output and process controls
- TCP State Change Alerts with downtime tracking
- Persistent Event History with filtering, CSV Export, and retention
- Availability / Uptime Statistics with coverage-aware outage reporting and CSV export
- Native Windows System Tray with background monitoring controls
- Provider-based Windows, Generic Webhook, and Microsoft Teams-compatible notifications
- Save / Load host lists
- Auto-load saved hosts
- Dark / Light theme
- Persisted local configuration
- PyInstaller EXE build support
- Custom application icon

Current released version: **v1.12.0**

Current recommended version for Health Watchdog / Incident History work: **v1.13.0**

Current recommended version for Notification Delivery History work: **v1.8.0**

Current recommended version for Availability / Uptime Statistics work: **v1.9.0**

Current recommended version for Device Groups / Planned Maintenance work: **v1.10.0**

---

## Public Repository Documentation Safety

Treat this repository and every tracked file as public information.

For all future changes:

- Use fictional, generic names such as `Demo-PLC`, `Test-Server`, `Gateway-01`, `Router-01`, `NAS-01`, `Device-01`, and `Printer-01`
- Use generic private addresses or reserved documentation ranges where examples need IP addresses
- Do not include company-specific examples, real machine identifiers, internal hostnames or domains, employee/user names, actual network topology, or real infrastructure naming conventions
- Never include credentials, passwords, API keys, tokens, private keys, Authorization headers, webhook secrets, or other secrets
- Keep public examples sanitized in tests, documentation, source comments, sample data, screenshots, and release notes
- Review both `README.md` and `README_TH.md` for public-safety issues whenever either is updated
- Review screenshots and demo media before publishing; do not silently edit sensitive images without a safe replacement workflow
- If a suspected real secret is found, do not print or duplicate its value; identify only the file and category, and recommend rotation
- Do not inspect ignored local user data unless the task explicitly requires it

---

## Primary Development Rules

Before modifying the project:

1. Inspect the current implementation first.
2. Preserve existing working behavior unless the task explicitly asks to change it.
3. Prefer small, focused changes over large rewrites.
4. Avoid unnecessary third-party dependencies.
5. Keep the application compatible with Windows 10/11.
6. Keep PyInstaller EXE compatibility.
7. Do not create a Git commit unless explicitly requested.
8. Do not delete or overwrite local user data/config files unless explicitly requested.

---

## Repository Layout

Keep the current release-oriented structure unless a task explicitly authorizes a larger migration:

- Application modules remain at repository root: `multi_port_checker.py`, `app_version.py`, `application_health.py`, `windows_startup.py`, `network_checks.py`, `monitoring_state.py`, `event_history.py`, `availability_report.py`, `notification_history.py`, `windows_tray.py`, `notification_models.py`, `notification_manager.py`, `windows_notifications.py`, and `webhook_notifications.py`
- Unit tests live under `tests/`
- Static application assets live under `assets/`
- Future sanitized documentation images belong under `docs/images/`
- `MultiPortChecker.spec` is the tracked canonical PyInstaller production configuration at repository root
- The changelog filename is `CHANGELOG.md`
- `README.md` and `README_TH.md` must remain synchronized under the bilingual documentation rules below
- Runtime/user data such as `events.db`, `mpc_config.json`, `p.json`, `list.json`, CSV exports, and saved host lists must not be committed or packaged

Canonical verification commands from repository root are:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q settings_backup.py settings_backup_ui.py app_version.py application_health.py windows_startup.py multi_port_checker.py network_checks.py monitoring_state.py event_history.py availability_report.py notification_history.py windows_tray.py notification_models.py notification_manager.py windows_notifications.py webhook_notifications.py tests
pyinstaller --clean --noconfirm MultiPortChecker.spec
```

Do not add unsanitized screenshots. A public documentation screenshot may be added only after review and must be stored under `docs/images/`.

---

## README.md / README_TH.md Maintenance — REQUIRED

Whenever a change affects user-visible behavior, installation, configuration, usage, build steps, features, screenshots, release information, or project structure, **README.md and README_TH.md must both be reviewed and updated in the same task**.

Do not leave either README outdated after implementing a feature.

The two README files must remain functionally synchronized. `README.md` is the canonical source for structure and technical facts unless the project explicitly changes that policy.

Codex must:

- Update both README files when user-visible features change
- Keep commands, download links, release links, screenshots, GIF paths, version information, limits, and feature names consistent
- Never update only one language and leave the other stale
- Never invent Thai-only or English-only features
- Preserve technical accuracy over literal translation

Examples that require both `README.md` and `README_TH.md` updates:

- New feature added
- Existing feature removed or renamed
- UI behavior changed
- New button, field, column, menu, or workflow
- New configuration option
- Config file format or location changed
- Save / Load behavior changed
- Auto Refresh behavior changed
- Ping or TCP checking behavior changed
- IP Scan feature added
- New dependency added
- Python version requirement changed
- PyInstaller build command changed
- New files added to the repository
- File/folder structure changed
- New release/version published
- EXE filename or download URL changed
- Screenshot or demo GIF changed

Updates to both README files should be concise and reflect the actual implementation.

### README sections to review when relevant

Review and update the appropriate sections, including:

- Project description
- Features
- Screenshot
- Demo GIF
- Download
- Installation
- Running from source
- Build as EXE
- Configuration
- Usage
- File structure
- Roadmap
- Release/version information

Do not add documentation for features that are not implemented.

---

## CHANGELOG.md Maintenance

If `CHANGELOG.md` exists, update it when a meaningful feature, fix, or behavior change is implemented.

Use semantic versioning where practical:

- PATCH: bug fix, e.g. `1.1.1`
- MINOR: backward-compatible feature, e.g. `1.2.0`
- MAJOR: breaking change, e.g. `2.0.0`

Do not bump the actual release/tag automatically unless explicitly requested.

When recommending a version bump, explain why.

---

## Network Monitoring Behavior

### Ping

Ping and TCP status must remain independent.

Valid example:

```text
192.168.1.1 | 443 | 1 ms | OFFLINE
```

This means:

- Host responds to ICMP Ping
- TCP port 443 is closed or unreachable

Do not treat Ping success as proof that a TCP service is ONLINE.

Do not treat Ping timeout as automatic proof that the host is offline because ICMP may be blocked while TCP remains reachable.

### Ping implementation

The application primarily targets Windows 10/11.

Ping handling should:

- Use the process return code to determine Ping success
- Support localized Windows output, including Thai Windows
- Parse common latency formats such as:
  - `time=7ms`
  - `time<1ms`
  - decimal values where practical
- Avoid relying only on English strings such as `Reply from`
- Return a safe fallback if latency cannot be parsed
- Never crash the application due to malformed Ping output

Keep non-GUI Ping parsing/helper logic testable outside Tkinter.

### TCP Port Checking

Preserve socket-based TCP checks unless a task explicitly asks to change them.

Current timeout behavior is approximately:

```text
1.5 seconds
```

TCP availability determines the table's ONLINE/OFFLINE service status.

---

## Tkinter Threading Rules — CRITICAL

Do not perform slow network operations directly on Tkinter's main UI thread.

This includes:

- Ping
- TCP connection checks
- Check All
- Check Selected
- Auto Refresh
- IP Range Scan
- DNS/network operations that may block

Use:

- `threading`
- or `concurrent.futures.ThreadPoolExecutor`

Use a bounded worker pool. Avoid creating an uncontrolled number of threads.

Tkinter widgets must only be modified from the main UI thread.

Use a safe mechanism such as:

```python
root.after(...)
```

to send UI updates back to Tkinter.

Do not call Treeview, Label, Button, Entry, or other Tkinter widget mutation methods directly from worker threads.

---

## Windows System Tray Architecture

System Tray changes must preserve these invariants:

- Tkinter widgets may only be read or modified on Tk's main thread
- Native tray callbacks must enqueue actions and marshal them through `root.after()` or an equivalent main-thread queue; they must never call Tk directly
- Only one tray icon and one native tray message loop may exist per application instance
- Only the existing Auto Refresh scheduling path may be used; tray commands must not create a second timer or executor
- Tray Open must restore the existing Tk root, never create another root
- Tray Check All, Start Auto Refresh, Stop Auto Refresh, Event History, and Notification Settings must reuse the existing application actions
- Tray Exit and every other real-exit path must converge on the canonical idempotent application shutdown
- Shutdown must remove the tray icon/message loop and preserve existing executor, Trace Route, Event History, and Tk cleanup behavior
- The Windows tray implementation must remain compatible with the tracked `MultiPortChecker.spec` and shared icon under `assets/`
- Do not add `pystray`, Pillow, pywin32, or another runtime dependency without explicit user approval and a concrete maintainability justification
- Update both `README.md` and `README_TH.md` for tray behavior changes, and keep all examples compliant with the mandatory public-repository safety rules

---

## Notification Framework Architecture

Notification changes must preserve these invariants:

- `TcpStateTracker` is the single canonical source of meaningful TCP state transitions; providers must never implement separate monitoring or transition logic
- Event History and provider notifications must consume the same canonical DOWN / RECOVERED transition without duplicating it
- Network notification delivery must run outside Tk's main thread on a bounded worker or queue
- Provider errors, timeouts, and retries must never break monitoring, Auto Refresh, Event History, or another provider
- Tray callbacks, notification results, and Settings UI updates must marshal to Tk through the existing main-thread dispatch path
- Webhook and Workflow endpoint URLs are sensitive; never print, log, export, commit, or expose full endpoints or their tokens in diagnostics
- External webhook providers must default to disabled for old and new configurations
- Tests must use mocks, fakes, or temporary localhost servers and must never call real external notification services
- Test Notification actions must not modify `TcpStateTracker`, Event History, or monitored target state
- Canonical application shutdown must stop accepting notification work, cancel pending retries where practical, and stop the notification worker without waiting indefinitely
- Do not add third-party notification or HTTP dependencies without explicit user approval and a concrete maintainability justification
- Keep `README.md` and `README_TH.md` synchronized for all notification behavior, configuration, security, and provider changes
- Public-repository documentation safety remains mandatory for provider examples, payloads, tests, comments, and release notes

### Notification Delivery History and Durable Retry

- Delivery History must never store endpoint URLs, endpoint paths, query tokens, credentials, Authorization headers, secret request headers, or response bodies
- Test Notifications must never enter Notification Delivery History or the durable retry queue
- The durable queue must remain bounded; delayed retries must have a finite schedule and must never run forever
- Permanent HTTP client/configuration failures such as 400, 401, 403, and 404 must not be automatically retried later
- Manual Retry must resolve and use the current provider configuration and current endpoint
- Provider Delivery History is independent from Event History; clearing or retrying deliveries must not add, remove, or modify TCP Event History
- Startup retry recovery must run outside blocking Tk startup work and feed the bounded notification worker
- Canonical shutdown must stop retry scheduling promptly and leave persisted retry state recoverable on restart
- SQLite statements and storage rules belong in the delivery-history module, not Tk-heavy UI code or provider classes
- Provider failures must remain isolated from monitoring, Event History, the UI, and other providers
- Public-repository safety remains mandatory for delivery records, tests, documentation, and diagnostics
- `README.md` and `README_TH.md` must remain synchronized for delivery-history and retry behavior

---

## Auto Refresh Rules

Auto Refresh must:

- Refresh both Ping and TCP status
- Keep the UI responsive
- Prevent overlapping network-check cycles
- Not start a new cycle while a previous cycle is still running
- Stop reliably when the user presses Stop Auto
- Avoid scheduling additional cycles after Stop Auto

---

## Availability Reporting Architecture

- Availability derives from retained Event History `DOWN` / `RECOVERED` records only; do not build a second monitoring engine or duplicate `TcpStateTracker`
- Unknown periods must never be treated as uptime
- Availability uses known monitored duration as its denominator, and Coverage must always expose known duration relative to the requested period
- Outages crossing report boundaries must be clipped with interval intersection
- Unresolved outages must be supported through the report end/current time and identified as ongoing
- Host + Port is the stable target identity; Device Name is a display label and must not merge different ports
- Ping-only status, Trace Route, Notification Delivery History, webhook results, and transient IP Range Scan rows do not affect TCP Availability
- Reporting calculations and CSV generation stay UI-independent; potentially slow report work runs outside Tk's main thread
- Reports are read-only and must not mutate Event History, Notification History, monitoring state, notifications, or retry state
- Event History retention and clearing directly limit report depth; do not invent hidden historical backup data
- Keep `README.md` and `README_TH.md` synchronized for all report behavior and preserve public-repository safety in report fixtures, exports, documentation, and diagnostics

## Device Groups and Planned Maintenance Architecture

- Host + Port remains the canonical target identity; groups are organizational metadata only and must not alter Ping, TCP state, Device Name, or monitoring sessions
- Maintenance state is independent from TCP state, and monitoring must continue throughout maintenance through the existing canonical `TcpStateTracker`
- Real DOWN / RECOVERED transitions during maintenance must remain persisted in Event History as availability evidence
- Operational Tk and provider notifications are suppressed while maintenance is active, and suppression must happen before `NotificationManager` enqueue
- Maintenance must not cancel, rewrite, or otherwise affect delivery/retry rows created before maintenance began
- Raw Availability must remain unchanged from the TCP-only calculation; Operational Availability excludes only known monitored duration inside persisted planned-maintenance intervals
- UNKNOWN time never becomes uptime or additional Coverage because of maintenance
- Historical maintenance reporting must reconstruct persisted `MAINTENANCE_STARTED` / `MAINTENANCE_ENDED` intervals rather than relying only on current config flags
- Restart expiry must be idempotent and must not create duplicate maintenance-end events or fabricate TCP transitions
- Do not create a second monitoring engine or reset tracker baselines for maintenance behavior
- Keep `README.md` and `README_TH.md` synchronized for all group, maintenance, notification-suppression, and reporting behavior
- Public-repository safety applies to group values, maintenance reasons, tests, exports, documentation, and diagnostics

---

## Host List and Config Compatibility

### Portable Settings Backup invariants

- Portable backups use an explicit safe allowlist; never dump or redact the entire config. Secrets and notification endpoints are omitted by default.
- Windows startup registry state is machine-local and must never be exported or changed by restore; the hidden-start preference is portable.
- Runtime SQLite history, delivery records, retry queues, and maintenance audit evidence are not settings backups.
- Active maintenance is not portable. New/Replace targets start inactive; Merge preserves matching destination maintenance.
- Host + Port is import identity. Import must not fabricate monitoring transitions, notifications, or historical events, and must leave existing retry rows untouched.
- Backup format version is independent from application version. Reject unsupported formats; ignore unknown fields without persisting them.
- Config writes remain atomic. Imports use validate/plan/write/apply and must create a secret-free pre-import safety backup before config mutation.
- Runtime backups belong beside writable config, never in `_MEIPASS`. Backup payloads never supply output paths or executable instructions.
- Keep focused comments explaining portability, endpoint preservation, rollback, and security invariants, and keep README EN/TH synchronized.
- `settings_backup.py` owns UI-independent validation, planning and persistence; `settings_backup_ui.py` owns the compact Tk dialogs.

### Health watchdog and incident invariants

- The watchdog extends the existing Health model; do not create a second monitoring engine.
- A target being OFFLINE is not application-health failure. Incidents must represent internal degradation only and must be fingerprint-deduplicated.
- Incident details are secret-safe and must never contain endpoints, tokens, credentials, payloads, full config or target inventory.
- Automatic recovery is bounded and rate-limited. Durable notification recovery must not duplicate delivery jobs.
- Database recovery is non-destructive; never drop, recreate or delete operational data automatically.
- Shutdown stops the watchdog before workers. Intentional worker/provider/tray shutdown must not create incidents.
- A hidden window must not remain inaccessible after tray failure; restore it through the Tk main thread when safe.
- Open incidents are never retention-pruned. Comments explain lifecycle, recovery, threading and failure-boundary invariants.
- Health preferences may be portable; incident history, recovery counters and watchdog runtime state are not.

Saved host records should remain backward-compatible with:

```json
{
  "host": "example.com",
  "port": 443
}
```

Runtime values such as:

- Ping latency
- ONLINE/OFFLINE state

should not be required in saved host-list data.

Ping is runtime monitoring state and normally should not be persisted.

Do not break existing user config files without an explicit migration strategy.

Local files such as:

```text
mpc_config.json
p.json
events.db
```

may contain user data. Do not modify, delete, or commit them unless explicitly requested.

If appropriate, ensure local config/user files are covered by `.gitignore`.

---

## Theme Behavior

Dark / Light theme functionality must remain compatible with existing configuration.

If theme persistence exists:

- Save the selected theme
- Restore it on application startup
- Do not reset the user's preference during unrelated feature work

New widgets should support both Dark and Light themes.

---

## IP Range Scan

If IP Range Scan is implemented or added:

- Keep the UI responsive
- Run scanning in background workers
- Use bounded concurrency
- Allow a reasonable range limit or warn on very large ranges
- Show Ping and TCP results independently
- Do not freeze the UI while scanning
- Prevent accidental overlapping scans
- Consider progress/status feedback for long scans
- Reuse existing Ping/TCP helper functions where practical

If no IP Range Scan currently exists, do not claim that it does in README.md or README_TH.md.

---

## Error Handling

The application must handle these without crashing:

- Invalid hostname
- Invalid IPv4 address
- Invalid port
- DNS failure
- Ping executable failure
- Ping timeout
- TCP timeout
- Connection refused
- Unreachable network
- Corrupted optional config file
- Missing icon/resource file

User-facing errors should be understandable and concise.

---

## PyInstaller / EXE Compatibility

The application must remain buildable as a standalone Windows EXE.

Target behavior:

- Python does not need to be installed on the target machine
- Tkinter resources continue working
- Application icon continues working
- Resource lookup works both:
  - when running from source
  - when running as a PyInstaller EXE

Do not introduce dependencies that break PyInstaller packaging without updating the build instructions.

If the build command or `.spec` file changes, update README.md and README_TH.md.

---

## Testing and Verification

After code changes:

1. Run Python syntax compilation/checks.
2. Run existing automated tests.
3. Add focused tests for new non-GUI helper logic where practical.
4. Verify the Tkinter application starts without exceptions.
5. Manually test the changed workflow.
6. If PyInstaller-related code changed, verify an EXE build when practical.
7. Review README.md, README_TH.md, and CHANGELOG.md for required updates.

For Ping-related changes, test at minimum:

- Reachable host + open port
- Reachable host + closed port
- Unreachable host
- `time=...ms` parsing
- `<1 ms` parsing
- Localized/fallback Ping output where practical

---

## Repository Hygiene

Do not commit generated or machine-local artifacts unless the repository explicitly tracks them.

Typical files/directories that should remain ignored:

```text
venv/
__pycache__/
build/
dist/
*.spec
mpc_config.json
p.json
list.json
events.db
```

Exception: `MultiPortChecker.spec` is intentionally tracked as the canonical build configuration and must be explicitly unignored after the generic `*.spec` rule.

Do not remove tracked build configuration just because it matches a generic ignore rule.

---

## Coding Style

Keep the code readable and maintainable.

Prefer:

- Small functions
- Clear names
- Type hints where useful
- Shared network helper functions
- Minimal duplication
- Standard library where practical

Avoid:

- Large unrelated rewrites
- Hidden behavioral changes
- Bare `except:` unless there is a strong reason
- Direct Tkinter updates from worker threads
- Unbounded thread creation
- Storing runtime Ping/status results in persistent host-list data

## Architecture Comments, Startup, and Diagnostics — REQUIRED

- Add concise comments or docstrings for non-obvious architecture, assumptions, invariants, lifecycle behavior, and recovery paths; explain why the constraint exists rather than restating the code
- Document Tk/main-thread boundaries and why worker or native callbacks marshal through `root.after()` or the existing main-thread queue
- Document persistent-state migrations near their implementation, including backward-compatibility and idempotency assumptions
- Document security-sensitive redaction and secret-exclusion rules near diagnostic, notification, and export implementations
- Document availability/maintenance interval math, especially clipping, merging, subtraction, UNKNOWN coverage, and Raw-versus-Operational assumptions
- Avoid redundant line-by-line comments, and update or remove comments whenever behavior changes so comments never become stale
- Diagnostics exports must remain secret-safe and aggregate-only by default; exclude endpoints, tokens, credentials, full config, Event History contents, and target/device inventory
- Windows startup registration must remain current-user-only, require no administrator rights, and never use HKLM
- Source mode must not register a developer Python interpreter or checkout path; real startup registration is for frozen/PyInstaller builds only
- Health diagnostics must query existing component state and must not create a second monitoring engine or duplicate lifecycle workers
- Application health must distinguish target OFFLINE/unreachable results from internal monitoring orchestration failure
- Any periodic Health-window Tk callback must be cancelled when the window closes and during canonical shutdown

---

## Expected Codex Workflow

For each task:

1. Inspect the relevant files.
2. Summarize the intended changes briefly.
3. Implement the requested feature/fix.
4. Preserve unrelated existing behavior.
5. Add/update tests where practical.
6. Run verification.
7. Review and update `README.md` and `README_TH.md` if the implementation affects documentation.
8. Update `CHANGELOG.md` for meaningful user-visible changes when appropriate.
9. Do not commit unless explicitly requested.
10. Report:
   - Files changed
   - Main functions/classes changed
   - Behavior added/fixed
   - Tests/checks run
   - README.md / README_TH.md / CHANGELOG.md changes
   - Compatibility considerations
   - Recommended version bump

---

## Current Ping Feature Baseline

The current Ping implementation baseline includes:

- Locale-tolerant Ping latency parsing
- Ping success based on process return code
- Support for `time=7ms`
- Support for `time<1ms`
- Support for localized labels
- Support for decimal-comma latency values
- Safe fallback to `Online` when Ping succeeds but latency cannot be parsed
- Independent Ping and TCP results
- Existing 1.5-second TCP timeout preserved
- Bounded background worker pool, currently up to 16 workers
- Check All / Check Selected / Auto Refresh executed outside Tkinter's main thread
- UI updates routed through `root.after()`
- Overlap prevention for Auto Refresh
- Config schema remains backward-compatible with `{host, port}` and supports optional `name`
- Focused unit tests for Ping helper logic

When modifying these areas, preserve this behavior unless the task explicitly requests a different design.
