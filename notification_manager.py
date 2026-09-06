"""Bounded notification delivery, persistence, and durable retry coordination."""

import queue
import threading
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable, Mapping, Optional, Protocol

from notification_history import STATUS_FAILED, NotificationHistoryStore, utc_now
from notification_models import (
    DeliveryResult, NotificationEvent, NotificationSettings,
    PROVIDER_GENERIC, PROVIDER_TEAMS,
)

DELAYED_RETRY_DELAYS = (300, 900, 3600)
WEBHOOK_PROVIDERS = (PROVIDER_GENERIC, PROVIDER_TEAMS)


def delayed_retry_seconds(delayed_retry_count: int,
                          retry_after_seconds: Optional[int] = None) -> int:
    index = min(max(0, int(delayed_retry_count)), len(DELAYED_RETRY_DELAYS) - 1)
    fixed = DELAYED_RETRY_DELAYS[index]
    if retry_after_seconds is None:
        return fixed
    return max(fixed, min(3600, max(0, int(retry_after_seconds))))


class NotificationProvider(Protocol):
    key: str
    display_name: str
    retryable: bool

    def deliver(self, event: NotificationEvent, timeout: int) -> DeliveryResult: ...


@dataclass(frozen=True)
class _DeliveryJob:
    event: NotificationEvent
    provider_key: str
    timeout: int
    retries: int
    delivery_id: Optional[int] = None
    delayed: bool = False
    manual: bool = False
    direct_provider: Optional[NotificationProvider] = None


class NotificationManager:
    """One bounded delivery worker plus a lightweight durable-retry scheduler."""

    def __init__(self, result_callback: Optional[Callable[[DeliveryResult], None]] = None,
                 *, history_store: Optional[NotificationHistoryStore] = None,
                 max_queue: int = 256,
                 retry_delays: tuple[float, ...] = (1.0, 3.0),
                 delayed_retry_delays: tuple[int, ...] = DELAYED_RETRY_DELAYS,
                 clock=utc_now, scheduler_interval: float = 1.0):
        self._result_callback = result_callback
        self._history = history_store
        self._queue = queue.Queue(maxsize=max_queue)
        self._retry_delays = retry_delays
        self._delayed_retry_delays = tuple(delayed_retry_delays)
        self._clock = clock
        self._scheduler_interval = max(0.01, float(scheduler_interval))
        self._stop_event = threading.Event()
        self._scheduler_wake = threading.Event()
        self._settings_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._active_lock = threading.Lock()
        self._active_delivery_ids = set()
        self._settings = NotificationSettings()
        self._providers: dict[str, NotificationProvider] = {}
        self._accepting = True
        self._shutdown_started = False
        self._startup_recovered = False
        self._thread = threading.Thread(target=self._worker, name="notification-worker", daemon=True)
        self._scheduler_thread = threading.Thread(
            target=self._scheduler, name="notification-retry-scheduler", daemon=True
        )
        self._thread.start()
        self._scheduler_thread.start()

    @property
    def worker_alive(self) -> bool:
        return self._thread.is_alive() or self._scheduler_thread.is_alive()

    def configure(self, settings: NotificationSettings,
                  providers: Mapping[str, NotificationProvider]) -> None:
        with self._settings_lock:
            self._settings = settings
            self._providers = dict(providers)
        if self._history and not self._startup_recovered:
            self._history.recover_interrupted(
                settings.retry_later_enabled, now=self._clock()
            )
            self._startup_recovered = True
        self._scheduler_wake.set()

    def enqueue(self, event: NotificationEvent) -> int:
        if event.test_only:
            return 0
        with self._lifecycle_lock:
            if not self._accepting:
                return 0
        with self._settings_lock:
            settings = self._settings
            keys = [key for key in settings.enabled_providers() if key in self._providers]
        queued = 0
        for key in keys:
            delivery_id = self._history.insert_delivery(event, key, now=self._clock()) if self._history else None
            if self._history and delivery_id is None:
                continue
            job = _DeliveryJob(event, key, settings.timeout_seconds,
                               settings.retry_count, delivery_id)
            if self._put_job(job):
                queued += 1
            elif delivery_id is not None:
                self._history.mark_failed(delivery_id, "UNKNOWN", "Notification queue is full")
        return queued

    def enqueue_test(self, provider: NotificationProvider, *, timeout: int = 5,
                     retries: int = 2) -> bool:
        return self._put_job(_DeliveryJob(
            NotificationEvent.test_notification(), provider.key, timeout, retries,
            direct_provider=provider,
        ))

    def retry_selected(self, delivery_id: int) -> bool:
        if not self._history:
            return False
        record = self._history.get(delivery_id)
        if not record or record.status != STATUS_FAILED:
            return False
        with self._settings_lock:
            settings = self._settings
            enabled = record.provider in settings.enabled_providers()
            provider_exists = record.provider in self._providers
        if not enabled or not provider_exists:
            self._publish(DeliveryResult(
                record.provider, False, "Provider is disabled.",
                error_category="PROVIDER_DISABLED", safe_summary="Provider is disabled"
            ))
            return False
        self._history.mark_queued(delivery_id)
        queued = self._put_job(_DeliveryJob(
            record.to_event(), record.provider, settings.timeout_seconds,
            settings.retry_count, delivery_id, manual=True,
        ))
        if not queued:
            self._history.mark_failed(delivery_id, "UNKNOWN", "Notification queue is full")
        return queued

    def retry_all_failed(self) -> int:
        if not self._history:
            return 0
        return sum(self.retry_selected(row.id)
                   for row in reversed(self._history.failed_deliveries()))

    def process_due_retries(self, limit: int = 100) -> int:
        if not self._history:
            return 0
        with self._settings_lock:
            settings = self._settings
            enabled = set(settings.enabled_providers())
            available = set(self._providers)
        if not settings.retry_later_enabled:
            return 0
        queued = 0
        for record in self._history.due_retries(self._clock(), limit=limit):
            if record.provider not in WEBHOOK_PROVIDERS:
                self._history.mark_failed(record.id, "UNKNOWN", "Delayed retry is unavailable")
                continue
            if record.provider not in enabled or record.provider not in available:
                continue
            if record.delayed_retry_count >= len(self._delayed_retry_delays):
                self._history.mark_failed(record.id, record.last_error_category or "UNKNOWN",
                                          record.last_error_summary or "Delivery failed")
                continue
            if self._put_job(_DeliveryJob(
                record.to_event(), record.provider, settings.timeout_seconds,
                settings.retry_count, record.id, delayed=True,
            )):
                queued += 1
        return queued

    def _put_job(self, job: _DeliveryJob) -> bool:
        with self._lifecycle_lock:
            if not self._accepting:
                return False
        if job.delivery_id is not None:
            with self._active_lock:
                if job.delivery_id in self._active_delivery_ids:
                    return False
                self._active_delivery_ids.add(job.delivery_id)
        try:
            self._queue.put_nowait(job)
            return True
        except queue.Full:
            if job.delivery_id is not None:
                with self._active_lock:
                    self._active_delivery_ids.discard(job.delivery_id)
            self._publish(DeliveryResult(
                job.provider_key, False, "Notification queue is full.",
                test_only=job.event.test_only, error_category="UNKNOWN",
                safe_summary="Notification queue is full",
            ))
            return False

    def _worker(self) -> None:
        while True:
            job = self._queue.get()
            try:
                if job is None:
                    return
                self._deliver_job(job)
            except Exception:
                if job.delivery_id is not None and self._history:
                    self._history.mark_failed(job.delivery_id, "UNKNOWN", "Delivery failed unexpectedly")
                self._publish(DeliveryResult(
                    job.provider_key, False, "Notification delivery failed unexpectedly.",
                    test_only=job.event.test_only, error_category="UNKNOWN",
                    safe_summary="Delivery failed unexpectedly",
                ))
            finally:
                if job is not None and job.delivery_id is not None:
                    with self._active_lock:
                        self._active_delivery_ids.discard(job.delivery_id)
                self._queue.task_done()

    def _deliver_job(self, job: _DeliveryJob) -> None:
        with self._settings_lock:
            provider = job.direct_provider or self._providers.get(job.provider_key)
            enabled = job.provider_key in self._settings.enabled_providers()
        if job.delivery_id is not None and (job.delayed or job.manual) and not enabled:
            disabled = DeliveryResult(
                job.provider_key, False, "Provider is disabled.",
                error_category="PROVIDER_DISABLED", safe_summary="Provider is disabled"
            )
            if job.manual and self._history:
                self._history.mark_failed(job.delivery_id, "PROVIDER_DISABLED", "Provider is disabled")
            self._publish(disabled)
            return
        if job.delayed and job.delivery_id is not None and self._history:
            self._history.begin_delayed_retry(job.delivery_id)
        if provider is None:
            self._finish_failure(job, DeliveryResult(
                job.provider_key, False, "Provider is disabled.",
                error_category="PROVIDER_DISABLED", safe_summary="Provider is disabled"
            ))
            return
        total_attempts = job.retries + 1 if provider.retryable else 1
        for attempt in range(total_attempts):
            if self._stop_event.is_set():
                self._preserve_interrupted(job)
                return
            if job.delivery_id is not None and self._history:
                self._history.record_attempt(job.delivery_id, now=self._clock())
            try:
                result = provider.deliver(job.event, job.timeout)
                if not isinstance(result, DeliveryResult):
                    raise TypeError("Provider returned an invalid delivery result")
            except Exception:
                result = DeliveryResult(
                    job.provider_key, False, "Notification delivery failed unexpectedly.",
                    retryable=provider.retryable, test_only=job.event.test_only,
                    error_category="UNKNOWN", safe_summary="Delivery failed unexpectedly",
                )
            if result.success:
                if job.delivery_id is not None and self._history:
                    self._history.mark_delivered(job.delivery_id, now=self._clock())
                self._publish(result)
                return
            if not result.retryable or attempt == total_attempts - 1:
                self._finish_failure(job, result)
                return
            delay_index = min(attempt, max(0, len(self._retry_delays) - 1))
            delay = self._retry_delays[delay_index] if self._retry_delays else 0
            if self._stop_event.wait(delay):
                self._preserve_interrupted(job)
                return

    def _finish_failure(self, job: _DeliveryJob, result: DeliveryResult) -> None:
        category = result.error_category or "UNKNOWN"
        summary = result.safe_summary or "Delivery failed"
        if job.delivery_id is not None and self._history:
            record = self._history.get(job.delivery_id)
            with self._settings_lock:
                retry_later = self._settings.retry_later_enabled
            may_delay = (
                not job.manual and retry_later
                and (result.delayed_retryable if result.delayed_retryable is not None else result.retryable)
                and job.provider_key in WEBHOOK_PROVIDERS and record is not None
                and record.delayed_retry_count < len(self._delayed_retry_delays)
            )
            if may_delay:
                index = min(record.delayed_retry_count, len(self._delayed_retry_delays) - 1)
                delay = self._delayed_retry_delays[index]
                if result.retry_after_seconds is not None:
                    delay = max(delay, min(3600, result.retry_after_seconds))
                self._history.schedule_retry(
                    job.delivery_id, self._clock() + timedelta(seconds=delay), category, summary
                )
                self._scheduler_wake.set()
            else:
                self._history.mark_failed(job.delivery_id, category, summary)
        self._publish(result)

    def _preserve_interrupted(self, job: _DeliveryJob):
        if job.delivery_id is None or not self._history:
            return
        with self._settings_lock:
            retry_later = self._settings.retry_later_enabled
        if retry_later and job.provider_key in WEBHOOK_PROVIDERS:
            self._history.schedule_retry(job.delivery_id, self._clock(), "NETWORK",
                                         "Delivery interrupted during shutdown")
        else:
            self._history.mark_failed(job.delivery_id, "UNKNOWN",
                                      "Delivery interrupted during shutdown")

    def _scheduler(self):
        while not self._stop_event.is_set():
            self.process_due_retries()
            self._scheduler_wake.wait(self._scheduler_interval)
            self._scheduler_wake.clear()

    def _publish(self, result: DeliveryResult) -> None:
        if self._result_callback is not None:
            try:
                self._result_callback(result)
            except Exception:
                pass

    def wait_until_idle(self, timeout: float = 5.0) -> bool:
        done = threading.Event()

        class _MarkerProvider:
            key = "marker"
            display_name = "Marker"
            retryable = False
            def deliver(self, event, timeout):
                del event, timeout
                done.set()
                return DeliveryResult(self.key, True, "Marker")

        return self._put_job(_DeliveryJob(
            NotificationEvent.test_notification(), "marker", 1, 0,
            direct_provider=_MarkerProvider(),
        )) and done.wait(timeout)

    def shutdown(self, timeout: float = 1.0) -> bool:
        with self._lifecycle_lock:
            if self._shutdown_started:
                return False
            self._shutdown_started = True
            self._accepting = False
        self._stop_event.set()
        self._scheduler_wake.set()
        while True:
            try:
                job = self._queue.get_nowait()
                if job is not None:
                    self._preserve_interrupted(job)
                    if job.delivery_id is not None:
                        with self._active_lock:
                            self._active_delivery_ids.discard(job.delivery_id)
                self._queue.task_done()
            except queue.Empty:
                break
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread is not threading.current_thread():
            self._thread.join(timeout)
        if self._scheduler_thread is not threading.current_thread():
            self._scheduler_thread.join(timeout)
        return True
