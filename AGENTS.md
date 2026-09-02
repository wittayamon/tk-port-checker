# AGENTS.md

## Project Overview

This repository contains **Multi Host Port Checker**, a Windows desktop network monitoring tool written in Python with Tkinter.

Main capabilities currently include:

- Add and remove multiple Host/IP + TCP Port targets
- Check TCP port availability
- Ping monitoring with latency display
- Ping and TCP status are intentionally independent
- Check Selected
- Check All
- Auto Refresh
- Background network checks so the Tkinter UI remains responsive
- Save / Load host lists
- Auto-load saved hosts
- Dark / Light theme
- Persisted local configuration
- PyInstaller EXE build support
- Custom application icon

Current recommended version after Ping monitoring was added: **v1.1.0**

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

## README.md Maintenance — REQUIRED

Whenever a change affects user-visible behavior, installation, configuration, usage, build steps, features, screenshots, release information, or project structure, **README.md must be reviewed and updated in the same task**.

Do not leave README.md outdated after implementing a feature.

Examples that require a README.md update:

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

README updates should be concise and reflect the actual implementation.

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

## Auto Refresh Rules

Auto Refresh must:

- Refresh both Ping and TCP status
- Keep the UI responsive
- Prevent overlapping network-check cycles
- Not start a new cycle while a previous cycle is still running
- Stop reliably when the user presses Stop Auto
- Avoid scheduling additional cycles after Stop Auto

---

## Host List and Config Compatibility

Saved host records should remain backward-compatible with:

```json
{
  "host": "google.com",
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

If no IP Range Scan currently exists, do not claim that it does in README.md.

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

If the build command or `.spec` file changes, update README.md.

---

## Testing and Verification

After code changes:

1. Run Python syntax compilation/checks.
2. Run existing automated tests.
3. Add focused tests for new non-GUI helper logic where practical.
4. Verify the Tkinter application starts without exceptions.
5. Manually test the changed workflow.
6. If PyInstaller-related code changed, verify an EXE build when practical.
7. Review README.md and CHANGELOG.md for required updates.

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
```

Exception: an existing `.spec` file may intentionally be tracked if the project uses it as the canonical build configuration. Inspect the repository before changing `.gitignore`.

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

---

## Expected Codex Workflow

For each task:

1. Inspect the relevant files.
2. Summarize the intended changes briefly.
3. Implement the requested feature/fix.
4. Preserve unrelated existing behavior.
5. Add/update tests where practical.
6. Run verification.
7. Review and update `README.md` if the implementation affects documentation.
8. Update `CHANGELOG.md` for meaningful user-visible changes when appropriate.
9. Do not commit unless explicitly requested.
10. Report:
   - Files changed
   - Main functions/classes changed
   - Behavior added/fixed
   - Tests/checks run
   - README/CHANGELOG changes
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
- Config schema remains `{host, port}`
- Focused unit tests for Ping helper logic

When modifying these areas, preserve this behavior unless the task explicitly requests a different design.
