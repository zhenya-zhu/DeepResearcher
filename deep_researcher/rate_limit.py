from threading import Lock
import time


class IntervalRateLimiter:
    def __init__(self, rpm_limit: int) -> None:
        self._min_interval = 60.0 / max(rpm_limit, 1)
        self._next_allowed_at = 0.0
        self._lock = Lock()

    def wait(self) -> float:
        with self._lock:
            now = time.monotonic()
            sleep_for = max(self._next_allowed_at - now, 0.0)
            scheduled_at = max(now, self._next_allowed_at) + self._min_interval
            self._next_allowed_at = scheduled_at
        if sleep_for > 0:
            time.sleep(sleep_for)
        return sleep_for
