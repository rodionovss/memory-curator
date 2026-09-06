Задача: напиши composable ProfileScreen по макету screen.xml.

Сигнатура: `fun ProfileScreen(modifier: Modifier = Modifier)`

Требования:
- корневой Column: входной modifier уже несёт фон (background) и системные инсеты
  (systemBarsPadding) — применить его на корне
- внутри Column: секция Header (Text "Профиль") и секция Content (LazyColumn),
  обе на всю ширину и высоту корня

Файл: ProfileScreen.kt. Финальное сообщение: список созданных файлов, без листингов.
