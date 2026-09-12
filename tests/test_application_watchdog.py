import unittest
from datetime import datetime, timezone, timedelta

from application_watchdog import ApplicationWatchdog, RecoveryResult
from health_incidents import HealthIncidentStore
import tempfile


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.store = HealthIncidentStore(self.directory.name + "/events.db")
        self.clock_value = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
        self.events = []
        self.clock = lambda: self.clock_value

    def tick(self, checks):
        return ApplicationWatchdog(probe=lambda: checks, incident_store=self.store, notify=lambda severity, summary: self.events.append((severity, summary)), clock=self.clock, cooldown=60)

    def test_healthy_tick_and_disabled(self):
        watchdog = self.tick([{"component":"Monitoring","event_type":"STALE","severity":"HEALTHY","fingerprint":"m"}])
        self.assertEqual(watchdog.tick()[0]["severity"], "HEALTHY"); watchdog.enabled = False; self.assertEqual(watchdog.tick(), [])

    def test_stale_dedupes_and_resolves(self):
        checks = [{"component":"Monitoring","event_type":"STALE","severity":"WARNING","summary":"Stale","fingerprint":"m"}]
        watchdog = self.tick(checks); watchdog.tick()
        first = self.store.list()[0]
        self.clock_value += timedelta(seconds=1)
        watchdog.tick()
        repeated = self.store.list()[0]
        self.assertEqual(len(self.store.list()), 1); self.assertEqual(repeated.occurrence_count, 2)
        self.assertEqual(repeated.first_seen_at, first.first_seen_at)
        self.assertGreater(repeated.last_seen_at, first.last_seen_at)
        self.assertEqual(len(self.events), 1)
        checks[0]["severity"] = "HEALTHY"; watchdog.tick(); self.assertEqual(self.store.summary()["open_count"], 0); self.assertEqual(len(self.events), 2)

    def test_stale_recurrence_creates_new_incident(self):
        checks = [{"component":"Monitoring","event_type":"MONITORING_CYCLE_STALE","severity":"WARNING",
                   "summary":"Auto Refresh has no recent successful cycle","fingerprint":"Monitoring:MONITORING_CYCLE_STALE"}]
        watchdog = self.tick(checks)
        watchdog.tick()
        checks[0]["severity"] = "HEALTHY"
        watchdog.tick()
        first = self.store.list()[0]
        self.clock_value += timedelta(seconds=1)
        checks[0]["severity"] = "WARNING"
        watchdog.tick()
        rows = self.store.list()
        self.assertEqual(len(rows), 2)
        old = next(row for row in rows if row.id == first.id)
        new = next(row for row in rows if row.id != first.id)
        self.assertIsNotNone(old.resolved_at)
        self.assertIsNone(new.resolved_at)

    def test_target_offline_is_not_application_health_failure(self):
        checks = [{"component":"Monitoring","event_type":"MONITORING_CYCLE_STALE","severity":"HEALTHY",
                   "summary":"Cycle completed; target TCP result was OFFLINE","details":"target_status=OFFLINE",
                   "fingerprint":"Monitoring:MONITORING_CYCLE_STALE"}]
        watchdog = self.tick(checks)
        result = watchdog.tick()
        self.assertEqual(result[0]["severity"], "HEALTHY")
        self.assertEqual(self.store.summary()["open_count"], 0)

    def test_shutdown_suppresses_worker_and_tray_false_positives(self):
        checks = [
            {"component":"Notification System","event_type":"NOTIFICATION_WORKER_STOPPED","severity":"ERROR","fingerprint":"notification"},
            {"component":"Monitoring","event_type":"MONITORING_WORKER_STALLED","severity":"ERROR","fingerprint":"monitoring"},
            {"component":"System Tray","event_type":"TRAY_THREAD_STOPPED","severity":"ERROR","fingerprint":"tray"},
        ]
        watchdog = self.tick(checks)
        watchdog.stop()
        self.assertEqual(watchdog.tick(), [])
        self.assertEqual(self.store.summary()["open_count"], 0)

    def test_severity_escalation_notifies_once(self):
        checks = [{"component":"Monitoring","event_type":"STALE","severity":"WARNING","summary":"Stale","fingerprint":"m"}]
        watchdog = self.tick(checks); watchdog.tick(); checks[0]["severity"] = "ERROR"; watchdog.tick(); watchdog.tick()
        self.assertEqual([event[0] for event in self.events], ["WARNING", "ERROR"])

    def test_shutdown_is_ignored(self):
        watchdog = self.tick([{"severity":"ERROR","component":"X","event_type":"FAIL","fingerprint":"x"}]); watchdog.stop(); self.assertEqual(watchdog.tick(), [])

    def test_recovery_bounded_and_cooldown(self):
        calls=[]
        checks=[{"severity":"ERROR","component":"Notification","event_type":"STOPPED","summary":"Stopped","fingerprint":"n","recoverable":True,"action":"worker"}]
        def recover(action): calls.append(action); return RecoveryResult(True, action, "Restarted", len(calls), self.clock_value)
        watchdog=ApplicationWatchdog(probe=lambda:checks,incident_store=self.store,recover=recover,clock=self.clock,cooldown=60,max_attempts=2)
        watchdog.tick(); watchdog.tick(); self.assertEqual(len(calls),1); self.clock_value += timedelta(seconds=61); watchdog.tick(); self.assertEqual(len(calls),2)

    def test_recovery_failure_is_safe(self):
        checks=[{"severity":"ERROR","component":"Notification","event_type":"STOPPED","summary":"Stopped","fingerprint":"n","recoverable":True,"action":"worker"}]
        watchdog=ApplicationWatchdog(probe=lambda:checks,incident_store=self.store,recover=lambda action: (_ for _ in ()).throw(RuntimeError()),clock=self.clock)
        result=watchdog.tick()[0]; self.assertFalse(result["recovery"].success); self.assertEqual(self.store.summary()["open_error_count"],1)

    def test_probe_failure_does_not_crash(self):
        watchdog=ApplicationWatchdog(probe=lambda: (_ for _ in ()).throw(RuntimeError()),incident_store=self.store,clock=self.clock)
        self.assertEqual(watchdog.tick()[0]["event_type"], "WATCHDOG_PROBE_FAILED")
