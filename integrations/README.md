# Memory Curator в OpenCode

Одна установка плагина (global):

```bash
cp integrations/curator-context.js ~/.config/opencode/plugins/
```

или project-level: `cp integrations/curator-context.js .opencode/plugins/`.

Перезапусти opencode — готово.

## Как работает (ADR 002, issue #28)

- хук **`chat.message`** — единственный поддерживаемый lifecycle hook:
  вызывается до сохранения сообщения и до генерации ответа (`session/prompt.ts`);
- плагин берёт текст первого сообщения, вызывает CLI-контракт
  `curator context '<текст задачи>'` и добавляет ranked context cards
  в `parts` сообщения — карточки попадают в контекст LLM без ручного
  вызова tool;
- изоляция от storage: плагин знает только CLI и JSON (ADR 002) — смена
  backend его не касается;
- одна доставка на сессию (re-delivery после session.deleted), повторное
  сообщение не шумит;
- ошибки retrieval глушатся: пустой контракт → нет доставки, сессия
  продолжается;
- ручной fallback остаётся: `curator query`, `curator get`,
  `curator context '<задача>'`.
