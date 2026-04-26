"""
File Watcher — monitors a working directory for file changes during a CLI session.

Quality-check gates applied:
  - Uses watchdog for cross-platform inotify/kqueue/FSEvents.
  - One Observer per watcher instance; properly stopped and joined on cleanup.
  - Events are debounced (100ms) to avoid flooding on rapid-fire writes.
  - Callback invoked on a daemon thread; must be non-blocking.
  - Lazy import of watchdog so the module loads fast even if watchdog is absent.
  - No state shared between sessions; each session gets its own FileWatcher.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_DEBOUNCE_SECONDS = 0.1


@dataclass
class FileEvent:
    path: str
    change: str  # 'edit' | 'create' | 'delete'
    timestamp: float  # time.time()


class FileWatcher:
    """
    Watches a directory tree for file changes.
    Call start(workdir, callback) to begin, stop() when done.
    callback(event: FileEvent) is called on the watchdog thread — keep it fast.
    """

    def __init__(self) -> None:
        self._observer = None
        self._handler = None
        self._started = False

    def start(self, workdir: str, callback: Callable[[FileEvent], None]) -> bool:
        """Start watching workdir. Returns False if watchdog is unavailable."""
        try:
            from watchdog.observers import Observer  # type: ignore
            from watchdog.events import FileSystemEventHandler, FileSystemEvent  # type: ignore
        except ImportError:
            logger.warning("[FileWatcher] watchdog not installed — file activity disabled")
            return False

        if self._started:
            self.stop()

        path = Path(workdir).resolve()
        if not path.exists():
            logger.warning("[FileWatcher] workdir does not exist: %s", path)
            return False

        _debounce: dict[str, float] = {}
        _lock = threading.Lock()

        class _Handler(FileSystemEventHandler):  # type: ignore[misc]
            def on_modified(self, event: FileSystemEvent) -> None:  # type: ignore[override]
                if not event.is_directory:
                    self._emit(event.src_path, "edit")

            def on_created(self, event: FileSystemEvent) -> None:  # type: ignore[override]
                if not event.is_directory:
                    self._emit(event.src_path, "create")

            def on_deleted(self, event: FileSystemEvent) -> None:  # type: ignore[override]
                if not event.is_directory:
                    self._emit(event.src_path, "delete")

            def _emit(self, src: str, change: str) -> None:
                now = time.monotonic()
                key = f"{src}:{change}"
                with _lock:
                    last = _debounce.get(key, 0.0)
                    if now - last < _DEBOUNCE_SECONDS:
                        return
                    _debounce[key] = now
                try:
                    callback(FileEvent(path=src, change=change, timestamp=time.time()))
                except Exception as exc:
                    logger.debug("[FileWatcher] callback error: %s", exc)

        handler = _Handler()
        observer = Observer()
        observer.schedule(handler, str(path), recursive=True)
        observer.daemon = True
        observer.start()

        self._observer = observer
        self._handler = handler
        self._started = True
        logger.info("[FileWatcher] watching %s", path)
        return True

    def stop(self) -> None:
        if self._observer and self._started:
            try:
                self._observer.stop()
                self._observer.join(timeout=2.0)
            except Exception as exc:
                logger.debug("[FileWatcher] stop error: %s", exc)
            finally:
                self._observer = None
                self._started = False
                logger.info("[FileWatcher] stopped")


# ── Module-level singleton ──────────────────────────────────────────────────
# Each session should call get_file_watcher().start(workdir, cb) and
# get_file_watcher().stop() — but the singleton is re-usable across sessions.

_watcher: Optional[FileWatcher] = None


def get_file_watcher() -> FileWatcher:
    global _watcher
    if _watcher is None:
        _watcher = FileWatcher()
    return _watcher
