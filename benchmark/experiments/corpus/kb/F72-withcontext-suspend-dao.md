---
type: Reference
tags: [coroutines, dao, withcontext]
---

# Не оборачивай suspend-DAO в withContext

Вызовы suspend-методов DAO не оборачиваются в withContext: скоуп вызова уже
корутинный, Room сам диспатчит запрос. Обёртка создаёт лишний прыжок
диспатчера и размывает ответственность слоя.

Исключение: настоящее blocking-IO (чтение файла с диска, BlockingQueue) —
обязан оборачиваться в withContext(Dispatchers.IO).
