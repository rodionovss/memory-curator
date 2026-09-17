---
type: Reference
tags: [retrofit, api, urls]
---

# Не дублируй префикс пути в Retrofit-методах

Базовый URL клиента уже содержит сегменты вроде /mobile/api. Пути @GET/@POST
в интерфейсах пишутся относительными: "settings", а не "/mobile/api/settings"
и не "mobile/api/settings". Задвоение префикса ломает итоговый URL (404).
