# Memory Curator в Claude Code

Одна команда:

```bash
curator install --claude
```

Без вопросов и флагов: ставит слэш-команды в `~/.claude/commands/`,
скиллы в `~/.claude/skills/` и одну секцию правил памяти в
`~/.claude/CLAUDE.md`. Фоновых процессов нет (решение 2026-10-03):
MCP-сервер и worker удалены, вся механика — в CLI `curator`.
Установка старой версии чистится автоматически: мёртвые MCP-записи
и plugin[]-артефакты удаляются, база мигрирует в `~/.curator/config.json`.

Перезапусти Claude Code — готово. Карта тем проекта —
`/curator-create-map`; контракт адаптера: [../README.md](../README.md);
подробности: [docs/getting-started.md](../../docs/getting-started.md).
