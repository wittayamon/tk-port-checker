"""Bounded background coordinator for independent notification providers."""

import queue
import threading
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Protocol

from notification_models import DeliveryResult, NotificationEvent, NotificationSettings


class NotificationProvider(Protocol):
    key: str
    display_name: str
    retryable: bool

    def deliver(self, event: NotificationEvent, timeout: int) -> DeliveryResult:
        ...


@dataclass(frozen=True)
class _DeliveryJob:
    event: NotificationEvent
    provider: NotificationProvider
    timeout: int
    retries: int


class NotificationManager:
    """Deliver provider jobs in order on one bounded background worker."""

    def __init__(
        self,
        result_callback: Optional[Callable[[DeliveryResult], None]] = None,
        *,
        max_queue: int = 256,
        retry_delays: tuple[float, ...] = (1.0, 3.0),
    ):
        self._result_callback = result_callback
        self._queue = queue.Queue(maxsize=max_queue)
        self._retry_delays = retry_delays
        self._stop_event = threading.Event()
        self._settings_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._settings = NotificationSettings()
        self._providers: dict[str, NotificationProvider] = {}
        self._accepting = True
        self._shutdown_started = False
        self._thread = threading.Thread(
            target=self._worker,
            name="notification-worker",
            daemon=True,
        )
        self._thread.start()

    @property
    def worker_alive(self) -> bool:
        return self._thread.is_alive()

    def configure(
        self,
        settings: NotificationSettings,
        providers: Mapping[str, NotificationProvider],
    ) -> None:
        with self._settings_lock:
            self._settings = settings
            self._providers = dict(providers)

    def enqueue(self, event: NotificationEvent) -> int:
        """Queue one job per enabled provider without blocking the caller."""
        with self._lifecycle_lock:
            if not self._accepting:
                return 0
        with self._settings_lock:
            settings = self._settings
            providers = [
                self._providers[key]
                for key in settings.enabled_providers()
                if key in self._providers
            ]
        queued = 0
        for provider in providers:
            if self._put_job(
                _DeliveryJob(
                    event,
                    provider,
                    settings.timeout_seconds,
                    settings.retry_count,
                )
            ):
                queued += 1
        return queued

    def enqueue_test(
        self,
        provider: NotificationProvider,
        *,
        timeout: int = 5,
        retries: int = 2,
    ) -> bool:
        return self._put_job(
            _DeliveryJob(
                NotificationEvent.test_notification(), provider, timeout, retries
            )
        )

    def _put_job(self, job: _DeliveryJob) -> bool:
        with self._lifecycle_lock:
            if not self._accepting:
                return False
        try:
            self._queue.put_nowait(job)
            return True
        except queue.Full:
            self._publish(
                DeliveryResult(
                    job.provider.key,
                    False,
                    f"{job.provider.display_name} was skipped because the notification queue is full.",
                    test_only=job.event.test_only,
                )
            )
            return False

    def _worker(self) -> None:
        while True:
            job = self._queue.get()
            try:
                if job is None:
                    return
                try:
                    self._deliver_job(job)
                except Exception:
                    self._publish(
                        DeliveryResult(
                            job.provider.key,
                            False,
                            f"{job.provider.display_name} delivery failed unexpectedly.",
                            test_only=job.event.test_only,
                        )
                    )
            finally:
                self._queue.task_done()

    def _deliver_job(self, job: _DeliveryJob) -> None:
        result = None
        total_attempts = job.retries + 1 if job.provider.retryable else 1
        for attempt in range(total_attempts):
            if self._stop_event.is_set():
                return
            try:
                result = job.provider.deliver(job.event, job.timeout)
                if not isinstance(result, DeliveryResult):
                    raise TypeError("Provider returned an invalid delivery result")
            except Exception:
                result = DeliveryResult(
                    job.provider.key,
                    False,
                    f"{job.provider.display_name} delivery failed unexpectedly.",
                    retryable=job.provider.retryable,
                    test_only=job.event.test_only,
                )
            if result.success or not result.retryable or attempt == total_attempts - 1:
                self._publish(result)
                return
            delay_index = min(attempt, max(0, len(self._retry_delays) - 1))
            delay = self._retry_delays[delay_index] if self._retry_delays else 0
            if self._stop_event.wait(delay):
                return

    def _publish(self, result: DeliveryResult) -> None:
        if self._result_callback is None:
            return
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

        if not self._put_job(
            _DeliveryJob(NotificationEvent.test_notification(), _MarkerProvider(), 1, 0)
        ):
            return False
        return done.wait(timeout)

    def shutdown(self, timeout: float = 1.0) -> bool:
        with self._lifecycle_lock:
            if self._shutdown_started:
                return False
            self._shutdown_started = True
            self._accepting = False
        self._stop_event.set()
        while True:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread is not threading.current_thread():
            self._thread.join(timeout)
        return True
