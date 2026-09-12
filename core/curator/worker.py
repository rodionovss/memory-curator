"""Фоновый worker для автономного цикла улучшения.

Запускается через cron или как долгоживущий процесс.
Периодически запускает improve loop (дубликаты, противоречия,
семантическое устаревание hypothesis по eval-гейту) и пишет отчёты.
Таймерного decay по неиспользованию нет — телеметрия остаётся
observability для человека, автоматика по ней не действует.

Использование:
    curator-worker                    # однократный запуск
    curator-worker --daemon          # демон каждые N минут (env: IMPROVE_INTERVAL_MINUTES)
    curator-worker --watch <dir>     # следить за директорией с сессиями

Конфигурация:
    MEMORY_BACKEND: "xmemory" | "local"
    XMEMORY_API_KEY / XMEMORY_INSTANCE_ID
    IMPROVE_INTERVAL_MINUTES: интервал между прогонами (default: 1440 = сутки)
    IMPROVE_REPORT_DIR: куда писать отчёты (default: ~/.curator/reports/)
    CURATOR_STATE_DIR: общий каталог состояния (default: ~/.curator)
    CURATOR_BASE_DIR: директория с .md файлами
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime


def get_backend():
    backend_type = os.getenv("MEMORY_BACKEND", "local")
    if backend_type == "xmemory":
        from curator.backend.xmemory import XMemoryBackend
        return XMemoryBackend(
            api_key=os.getenv("XMEMORY_API_KEY", ""),
            instance_id=os.getenv("XMEMORY_INSTANCE_ID", ""),
        )
    else:
        from curator.backend.local import LocalBackend
        return LocalBackend()


def run_improve_cycle(backend, report_dir: Path, base_dir: Path | None = None) -> dict:
    from curator.improve_loop import ImproveLoop
    improve = ImproveLoop(backend)
    report = improve.run()

    # Таймерного decay НЕТ (осознанно): время не делает факт ложным —
    # вечное редкое знание (личные правила) не должно гнить молчанием.
    # Телеметрия использования — observability для человека (curator
    # feedback / report), автоматика по ней не действует.

    # Жизненный цикл в .md: задеприкейтнутые improve-циклом → [УСТАРЕЛО]
    from curator.routing.map_router import find_map_path
    if base_dir is not None and report.deprecated and find_map_path() is None:
        from curator.sync_engine import SyncEngine
        sync = SyncEngine(backend, base_dir)
        for fact in report.deprecated:
            try:
                sync.rewrite_status(fact)
            except Exception as e:
                print(f"  ⚠ write-back в .md не удался для '{fact.title[:50]}': {e}")

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    report_file = report_dir / f"improve_{timestamp}.json"

    report_data = {
        "timestamp": datetime.now().isoformat(),
        "stats": report.stats,
        "duplicates": [
            {"title1": f1.title, "title2": f2.title}
            for f1, f2 in report.duplicates
        ],
        "stale": [
            {"title": f.title, "status": f.status}
            for f in report.stale
        ],
    }

    if report.metrics_before and report.metrics_after:
        report_data["metrics"] = {
            "before": {"query_coverage": report.metrics_before.query_coverage,
                       "total_facts": report.metrics_before.total_facts,
                       "verified_percent": report.metrics_before.verified_percent,
                       "stale_percent": report.metrics_before.stale_percent},
            "after": {"query_coverage": report.metrics_after.query_coverage,
                      "total_facts": report.metrics_after.total_facts,
                      "verified_percent": report.metrics_after.verified_percent,
                      "stale_percent": report.metrics_after.stale_percent},
        }

    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report_data, ensure_ascii=False, indent=2))

    return report_data


def run_daemon(backend, report_dir: Path, interval_minutes: int):
    """Запустить демон — периодический improve loop."""
    print(f"[curator-worker] Демон запущен. Интервал: {interval_minutes} мин. Отчёты: {report_dir}")
    base_dir = _base_dir_from_env()

    while True:
        print(f"[curator-worker] Запуск цикла улучшения в {datetime.now().isoformat()}")
        try:
            data = run_improve_cycle(backend, report_dir, base_dir=base_dir)
            print(f"  Фактов: {data['stats']['total_facts']}, "
                  f"дубликатов: {data['stats']['duplicates_found']}, "
                  f"устаревших: {data['stats']['stale_found']}")
        except Exception as e:
            print(f"  Ошибка: {e}")

        time.sleep(interval_minutes * 60)


def watch_directory(backend, watch_dir: Path):
    """Следить за директорией с .md файлами — при изменениях переиндексировать."""
    from curator.analyzers.ingest import ingest_directory
    from curator.gatekeeper import Gatekeeper

    gk = Gatekeeper(backend, check_duplicates=False)
    known_mtimes = {}

    print(f"[curator-worker] Наблюдение за {watch_dir}")

    while True:
        for md_file in sorted(watch_dir.rglob("*.md")):
            try:
                mtime = md_file.stat().st_mtime
            except OSError:
                continue  # файл удалён между rglob и stat
            if md_file in known_mtimes and known_mtimes[md_file] == mtime:
                continue
            known_mtimes[md_file] = mtime
            print(f"[curator-worker] Изменился: {md_file.relative_to(watch_dir)}")
            try:
                saved = ingest_directory(watch_dir, backend, gk)
                print(f"  Сохранено: {saved} фактов")
            except Exception as e:
                print(f"  Ошибка: {e}")

        time.sleep(30)


def _base_dir_from_env() -> Path:
    return Path(os.getenv("CURATOR_BASE_DIR", os.path.expanduser("~/Documents/AI/personal/learnings")))


def _report_dir_from_env() -> Path:
    from curator.state import env_path
    return env_path("IMPROVE_REPORT_DIR", "reports")


def main():
    report_dir = _report_dir_from_env()
    backend = get_backend()

    if "--watch" in sys.argv:
        idx = sys.argv.index("--watch")
        watch_dir = Path(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else _base_dir_from_env()
        watch_directory(backend, watch_dir)
    elif "--daemon" in sys.argv:
        interval = int(os.getenv("IMPROVE_INTERVAL_MINUTES", "1440"))
        run_daemon(backend, report_dir, interval)
    else:
        data = run_improve_cycle(backend, report_dir, base_dir=_base_dir_from_env())
        print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
