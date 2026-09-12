"""One bounded watchdog for application orchestration, never for target state.

The watchdog consumes lightweight callbacks owned by the application.  It does
not run network checks, create a second monitoring engine, or touch Tk widgets.
Recovery callbacks are rate-limited because durable notification state must not
be blindly re-enqueued after a worker failure.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from application_health import ERROR, HEALTHY, WARNING

WATCHDOG_INTERVAL_SECONDS = 15
MAX_AUTO_RECOVERY_ATTEMPTS = 2
RECOVERY_COOLDOWN_SECONDS = 60


@dataclass(frozen=True)
class RecoveryResult:
    success: bool
    action: str
    safe_summary: str
    attempt_number: int
    timestamp: datetime


class ApplicationWatchdog:
    """Deterministic tick engine; scheduling remains with Tk root.after."""

    def __init__(self, *, probe: Callable[[], list[dict]], incident_store=None,
                 notify: Optional[Callable[[str, str], None]] = None,
                 recover: Optional[Callable[[str], RecoveryResult]] = None,
                 clock=None, max_attempts=MAX_AUTO_RECOVERY_ATTEMPTS,
                 cooldown=RECOVERY_COOLDOWN_SECONDS):
        self.probe = probe
        self.incident_store = incident_store
        self.notify = notify
        self.recover = recover
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.max_attempts, self.cooldown = int(max_attempts), float(cooldown)
        self.enabled = True
        self.shutting_down = False
        self.last_tick = None
        self.last_duration_ms = None
        self._attempts = {}
        self._last_attempt = {}
        self._notified = {}

    @property
    def running(self):
        return self.enabled and not self.shutting_down

    def stop(self):
        self.shutting_down = True

    def _fingerprint(self, check):
        return str(check.get("fingerprint") or f"{check.get('component','Health')}:{check.get('event_type','DEGRADED')}")

    def tick(self):
        """Run isolated lightweight checks; one bad probe cannot stop later checks."""
        if not self.running:
            return []
        started = self.clock(); results = []
        try:
            checks = self.probe() or []
        except Exception:
            checks = [{"component": "Watchdog", "event_type": "WATCHDOG_PROBE_FAILED", "severity": WARNING, "summary": "Health probe failed", "fingerprint": "Watchdog:probe"}]
        for check in checks:
            if not isinstance(check, dict): continue
            fingerprint = self._fingerprint(check)
            bad = check.get("severity") in (WARNING, ERROR)
            if bad:
                recovery = None
                if check.get("recoverable") and self.recover:
                    now = started.timestamp(); last = self._last_attempt.get(fingerprint, -1e99)
                    count = self._attempts.get(fingerprint, 0)
                    if count < self.max_attempts and now - last >= self.cooldown:
                        self._attempts[fingerprint] = count + 1; self._last_attempt[fingerprint] = now
                        try: recovery = self.recover(check.get("action", fingerprint))
                        except Exception: recovery = RecoveryResult(False, str(check.get("action", "recovery")), "Recovery failed", count + 1, started)
                        check = {**check, "recovery": recovery}
                if self.incident_store:
                    incident = self.incident_store.record(component=check.get("component", "Health"), severity=check.get("severity", WARNING), event_type=check.get("event_type", "DEGRADED"), summary=check.get("summary", "Health condition detected"), details=check.get("details", ""), fingerprint=fingerprint, now=started, recovery_action=getattr(recovery, "action", ""), recovery_result=getattr(recovery, "safe_summary", ""))
                    previous = self._notified.get(fingerprint)
                    rank = {WARNING: 1, ERROR: 2}.get(check.get("severity"), 0)
                    previous_rank = {WARNING: 1, ERROR: 2}.get(previous, 0)
                    if incident and (previous is None or rank > previous_rank):
                        self._notified[fingerprint] = check.get("severity")
                        if self.notify: self.notify(check.get("severity", WARNING), check.get("summary", "Health condition detected"))
                results.append(check)
            else:
                if self.incident_store:
                    resolved = self.incident_store.resolve(fingerprint, recovery_action=check.get("recovery_action", ""), recovery_result=check.get("recovery_result", ""), now=started)
                    if resolved and self.notify and fingerprint in self._notified:
                        self._notified.pop(fingerprint, None); self.notify("RECOVERED", f"{check.get('component', 'Application')} recovered")
                results.append(check)
        self.last_tick = started; self.last_duration_ms = max(0.0, (self.clock() - started).total_seconds() * 1000)
        return results
