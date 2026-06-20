"""Persistent, process-safe rate limiter.

The handelsregister.de Nutzungsordnung (terms of use, based on §9 HGB) forbids
more than 60 retrievals per hour. Their FAQ warns that automated mass querying
beyond this may be treated as a criminal offence (§§303a, b StGB). This limiter
enforces a sliding-window cap shared across all processes on the machine, so an
agent firing tools in a loop cannot blow past the limit.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

try:  # POSIX file locking; degrades gracefully on platforms without fcntl
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore


class RateLimitError(RuntimeError):
    """Raised when the hourly request budget is exhausted."""

    def __init__(self, retry_after_seconds: float):
        self.retry_after_seconds = retry_after_seconds
        mins = int(retry_after_seconds // 60)
        secs = int(retry_after_seconds % 60)
        super().__init__(
            f"Rate limit reached: handelsregister.de allows at most "
            f"60 requests/hour. Retry in ~{mins}m{secs:02d}s."
        )


class RateLimiter:
    """Sliding-window limiter persisted to a JSON file under the temp dir."""

    def __init__(self, max_per_hour: int = 60, state_path: Path | None = None):
        self.max_per_hour = max_per_hour
        self.window_seconds = 3600
        self.state_path = state_path or (
            Path(tempfile.gettempdir()) / "handelsregister_mcp_ratelimit.json"
        )

    def _read(self) -> list[float]:
        try:
            return json.loads(self.state_path.read_text())
        except (FileNotFoundError, ValueError):
            return []

    def _write(self, timestamps: list[float]) -> None:
        self.state_path.write_text(json.dumps(timestamps))

    def _prune(self, timestamps: list[float], now: float) -> list[float]:
        return [t for t in timestamps if now - t < self.window_seconds]

    def check_and_consume(self) -> None:
        """Consume one request slot or raise RateLimitError."""
        with _FileLock(self.state_path):
            now = time.time()
            timestamps = self._prune(self._read(), now)
            if len(timestamps) >= self.max_per_hour:
                oldest = min(timestamps)
                raise RateLimitError(self.window_seconds - (now - oldest))
            timestamps.append(now)
            self._write(timestamps)

    def status(self) -> dict:
        with _FileLock(self.state_path):
            now = time.time()
            timestamps = self._prune(self._read(), now)
            remaining = max(0, self.max_per_hour - len(timestamps))
            reset_in = (
                int(self.window_seconds - (now - min(timestamps))) if timestamps else 0
            )
            return {
                "max_per_hour": self.max_per_hour,
                "used_last_hour": len(timestamps),
                "remaining": remaining,
                "window_resets_in_seconds": reset_in,
            }


class _FileLock:
    """Best-effort advisory lock around the state file."""

    def __init__(self, target: Path):
        self.lock_path = target.with_suffix(target.suffix + ".lock")
        self._fh = None

    def __enter__(self):
        self._fh = open(self.lock_path, "w")
        if fcntl is not None:
            fcntl.flock(self._fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        if self._fh is not None:
            if fcntl is not None:
                fcntl.flock(self._fh, fcntl.LOCK_UN)
            self._fh.close()
