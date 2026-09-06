# Memory Curator в Claude Code

Одна команда:

```bash
curator install --claude
```

Спросит, куда класть базу знаний (любой путь, по умолчанию
`~/memory-curator`), затем сам:

- пишет `.mcp.json` в текущий проект (MCP-сервер, тулзы `curator_*`);
- ставит слэш-команды в `~/.claude/commands/` (`/curator-save`,
  `/curator-create-map`, `/curator-status` и другие);
- ставит скиллы в `~/.claude/skills/` (curator-save и
  curator-create-map);
- поднимает фоновый worker самоулучшения.

Перезапусти Claude Code в проекте — готово. Карта документации проекта —
`/curator-create-map`, изоляция состояния проекта — `/curator-setup`;
подробности: `docs/getting-started.md`.
