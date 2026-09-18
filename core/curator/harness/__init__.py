"""Health-чеки интеграций с харнесами (OpenCode сейчас; Claude Code, Codex -
по мере появления).

Агрегатор integration_status() собирает чеки всех харнесов: server.py и
control.py импортируют только его - добавление харнеса не трогает
потребителей. Один харнес - один файл (порог перехода в папку: свои
подсистемы/ресурсы, а не просто рост файла).
"""

from curator.harness import opencode


def integration_status(state_dir=None) -> list[tuple[bool, str]]:
    """Все чеки всех харнесов: [(ok, сообщение), ...]."""
    checks: list[tuple[bool, str]] = []
    checks.extend(opencode.checks(state_dir))
    return checks
