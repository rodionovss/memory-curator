---
type: Reference
tags: [compose, rtl, textalign]
---

# Порт textAlignment="viewStart" — без явного TextAlign

Compose Text по умолчанию RTL-aware: выравнивание по logical start уже
поведение по умолчанию. При переносе XML textAlignment="viewStart" не задавай
textAlign явно (TextAlign.Start / TextAlign.Left): явное значение
приклеивает выравнивание и ломает RTL-порты. Дефолт — корректный порт.
