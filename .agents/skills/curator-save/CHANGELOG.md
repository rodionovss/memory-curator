# Changelog

## 0.2.0-candidate

- Разделён trigger-wrapper `SKILL.md` и подробный `playbook.md`.
- Добавлена последовательная проверка изменения понимания, evidence,
  переносимости, атомарности и типа утверждения.
- Сохранён read-only protection; сохранение переведено на flow
  `curator_session_capture` → `curator_capture_approve` →
  `curator-update-docs` → `curator_capture_complete`.
- Версия ожидает holdout eval и не считается принятой.

## 0.1.0

- Исходный workflow сохранения через `/curator-save`.
