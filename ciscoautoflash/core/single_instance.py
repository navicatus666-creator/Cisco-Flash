from __future__ import annotations

import os
import platform
import tempfile
from pathlib import Path


class SingleInstanceError(RuntimeError):
    pass


class SingleInstanceGuard:
    def __init__(self, name: str):
        self.name = name
        self._handle = None
        self._lock_path = Path(tempfile.gettempdir()) / f"{name}.lock"

    def acquire(self) -> None:
        if platform.system() == "Windows":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.CreateMutexW(None, False, self.name)
            if not handle:
                raise SingleInstanceError("Не удалось создать mutex приложения.")
            already_exists = kernel32.GetLastError() == 183
            if already_exists:
                kernel32.CloseHandle(handle)
                raise SingleInstanceError("Приложение уже запущено.")
            self._handle = handle
            return
        if self._lock_path.exists():
            raise SingleInstanceError("Приложение уже запущено.")
        self._lock_path.write_text(str(os.getpid()), encoding="utf-8")

    def release(self) -> None:
        if platform.system() == "Windows" and self._handle is not None:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None
            return
        try:
            if self._lock_path.exists():
                self._lock_path.unlink()
        except OSError:
            pass
