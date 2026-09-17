---
type: Reference
tags: [compose, modifier, insets]
---

# Входной modifier применяется один раз на корне composable

Системные инсеты (systemBarsPadding) и фон (background) приходят во входном
modifier извне. Корневой layout применяет его один раз; дочерним элементам —
новые Modifier, а не передача входного. Передача детям даёт двойные инсеты
и двойной фон.
