"""Обратная связь по использованию: отслеживает какие факты запрашиваются."""

import os
import time
import json
from contextlib import contextmanager
from pathlib import Path
from collections import defaultdict

from curator.state import env_path

if os.name != "nt":
    import fcntl


def _default_entry() -> dict:
    return {"count": 0, "last_access": 0.0}


class RetrievalFeedback:
    """Отслеживает usage фактов через query-запросы.

    Записывают несколько процессов (MCP-сервер, CLI, worker): каждая запись —
    read-modify-write под advisory-файллоком (flock), счётчики параллельных
    процессов не теряются. Запись атомарна (tmp с pid + os.replace). Чтения
    всегда свежие — с диска. Телеметрия: сбой записи не валит вызвавшую тулзу.
    """

    def __init__(self, storage_path: str | None = None):
        # Тесты и демо изолируют телеметрию через CURATOR_USAGE_PATH —
        # инвариант: ничего, кроме прод-кода, не пишет в ~/.curator/ пользователя
        self.storage_path = Path(storage_path).expanduser() if storage_path else env_path("CURATOR_USAGE_PATH", "usage.json")
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.storage_path.with_suffix(self.storage_path.suffix + ".lock")

    @contextmanager
    def _flocked(self):
        """Advisory-лок: сериализует read-modify-write между процессами."""
        if os.name == "nt":
            import ctypes
            import hashlib
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            name = "Local\\memory-curator-" + hashlib.sha256(
                str(self._lock_path.resolve()).lower().encode()
            ).hexdigest()
            mutex = kernel32.CreateMutexW(None, False, name)
            if not mutex:
                raise OSError(ctypes.get_last_error(), "CreateMutexW failed")
            try:
                if kernel32.WaitForSingleObject(mutex, 0xFFFFFFFF) not in (0, 0x80):
                    raise OSError(ctypes.get_last_error(), "WaitForSingleObject failed")
                try:
                    yield
                finally:
                    kernel32.ReleaseMutex(mutex)
            finally:
                kernel32.CloseHandle(mutex)
        else:
            with open(self._lock_path, "a+b") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def _read_disk(self) -> dict:
        if self.storage_path.exists():
            try:
                raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    # Битые записи (не dict, нечисловые поля) не должны
                    # валить чтение телеметрии
                    return {k: v for k, v in raw.items()
                            if isinstance(k, str) and isinstance(v, dict)
                            and isinstance(v.get("count"), (int, float))
                            and isinstance(v.get("last_access"), (int, float))}
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _write_disk(self, data: dict) -> None:
        tmp = self.storage_path.with_name(f"{self.storage_path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self.storage_path)

    def record_query(self, query_result_count: int, accessed_titles: list[str]):
        """Записать что N фактов были возвращены в ответ на запрос."""
        try:
            with self._flocked():
                data = self._read_disk()
                for title in accessed_titles:
                    entry = data.setdefault(title, _default_entry())
                    entry["count"] += 1
                    entry["last_access"] = time.time()
                self._write_disk(data)
        except OSError:
            pass

    def record_save(self, title: str):
        """Записать сохранение нового факта."""
        try:
            with self._flocked():
                data = self._read_disk()
                if title not in data:
                    data[title] = {**_default_entry(), "last_access": time.time()}
                self._write_disk(data)
        except OSError:
            pass

    def usage_map(self) -> dict[str, dict]:
        """Свежая карта title → {count, last_access} с диска (для ranking)."""
        return dict(self._read_disk())

    def get_stats(self, top_n: int = 10) -> list[dict]:
        """Топ-N самых используемых фактов (свежие данные с диска)."""
        counts = defaultdict(_default_entry, self._read_disk())
        sorted_items = sorted(
            counts.items(),
            key=lambda x: x[1]["count"],
            reverse=True,
        )
        return [
            {"title": title, "count": data["count"], "last_access": data["last_access"]}
            for title, data in sorted_items[:top_n]
            if data["count"] > 0
        ]

    def get_unused(self, min_days: int = 90) -> list[str]:
        """Факты к которым не обращались > N дней (кандидаты на deprecation)."""
        counts = defaultdict(_default_entry, self._read_disk())
        cutoff = time.time() - (min_days * 86400)
        return [
            title
            for title, data in counts.items()
            if data["last_access"] < cutoff
        ]
