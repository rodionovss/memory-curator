# Memory Curator Documentation

## Source Of Truth

- Код и тесты определяют фактическое поведение системы.
- `.agents/skills/` содержит канонические runtime skills продукта.
- `design/decisions/` содержит принятые архитектурные решения и их причины.
- `design/backlog.md` содержит текущие продуктовые задачи.
- `docs/` содержит актуальные пользовательские и operational guides.
- `benchmark/` содержит воспроизводимые эксперименты и их evidence.
- `demo/` содержит сценарии демонстрации, а не нормативные правила.
- `.opencode/superpowers/` содержит локальные планы и specs текущей работы агента
  и не коммитится.

## Historical Documents

`design/spec.md`, `design/requirements.md`, `docs/anketa.md` и
`PRESENTATION.md` сохраняются как история решений и сдачи. Они не
переопределяют код, тесты, skills или `design/decisions/`.

## Skills

Каждый продуктовый skill живёт в `.agents/skills/<name>/` и имеет структуру:

```text
<name>/
  SKILL.md       # trigger и ссылка на workflow
  playbook.md    # подробный workflow
  manifest.yaml  # версия и статус
  CHANGELOG.md   # изменения версий
  references/    # дополнительные материалы, если нужны
  evals/         # тестовые сценарии skill, если применимо
```

OpenCode должен использовать прямой symlink на `.agents/skills/<name>`. Копия
в `Documents/AI/skills` не является source of truth.

## Private Data

Личные session transcripts, базы, локальные predictions и gold-разметки не
коммитятся. Для extraction eval они хранятся в
`benchmark/extraction/local/`, который закрыт `.gitignore`.
