"""Unit-тесты детерминированного расширения запроса алиасами (retrieval v2).

Контракт (задача 8): расширение без LLM, case-insensitive, multi-word
алиасы матчатся longest-first с поглощением диапазона, дубликаты
расширенных терминов убираются с сохранением первого-seen порядка,
общие слова (screen/feature/code) не расширяются никогда.
"""

from curator.query_expansion import (
    expand_query,
    expand_query_detailed,
    load_aliases,
)

ALIASES = {
    "dao": ["repository", "suspend", "room"],
    "rtl": ["viewStart", "TextAlign", "right-to-left"],
    "blocking io": ["file read", "Dispatchers.IO", "withContext"],
    "viewmodel factory": ["IntoMap", "ViewModelKey", "Dagger"],
}


class TestExpandQueryMechanics:
    def test_сопоставление_без_учёта_регистра(self):
        assert expand_query("DAO и Dao", ALIASES) == expand_query("dao и dao", ALIASES)
        assert expand_query("dao", ALIASES) == ["repository", "suspend", "room"]

    def test_multi_word_алиас_матчится_фразой(self):
        assert expand_query("проблема Blocking IO в чтении", ALIASES) == [
            "file read", "Dispatchers.IO", "withContext",
        ]

    def test_multi_word_длиннее_поглощает_одиночный_токен(self):
        aliases = {"blocking io": ["x"], "io": ["y"]}
        # «io» внутри «blocking io» поглощён: одиночный ключ не срабатывает
        assert expand_query("blocking io здесь", aliases) == ["x"]
        # отдельное «io» вне поглощённого диапазона — срабатывает
        assert expand_query("blocking io и io", aliases) == ["x", "y"]

    def test_дубли_терминов_убираются_первый_seen_порядок(self):
        aliases = {"dao": ["room", "x"], "orm": ["room", "y"]}
        assert expand_query("dao orm", aliases) == ["room", "x", "y"]

    def test_дедуп_одинаковых_ключей_в_тексте(self):
        # один и тот же ключ дважды в триггере → термины один раз
        assert expand_query("dao и снова DAO", ALIASES) == [
            "repository", "suspend", "room",
        ]

    def test_без_совпадений_пусто(self):
        assert expand_query("рецепт борща", ALIASES) == []
        assert expand_query("", ALIASES) == []
        assert expand_query("dao", {}) == []

    def test_word_boundary_не_лезет_внутрь_слов(self):
        assert expand_query("download", {"load": ["x"]}) == []
        # дефис — не \w: «suspend-DAO» матчится
        assert expand_query("suspend-DAO", ALIASES) == ["repository", "suspend", "room"]

    def test_детерминированность(self):
        text = "DAO, RTL и blocking IO вперемешку"
        assert expand_query(text, ALIASES) == expand_query(text, ALIASES)


class TestGenericWords:
    def test_общие_слова_не_расширяются(self):
        aliases = {"screen": ["ui"], "feature": ["x"], "code": ["y"], "dao": ["room"]}
        assert expand_query("экранный screen feature code", aliases) == []

    def test_узкие_термины_в_том_же_словаре_работают(self):
        aliases = {"screen": ["ui"], "dao": ["room"]}
        assert expand_query("screen dao", aliases) == ["room"]


class TestDetailed:
    def test_ключ_и_термины_возвращаются_для_отладки(self):
        detailed = expand_query_detailed("DAO и RTL", ALIASES)
        assert detailed == [
            ("dao", ["repository", "suspend", "room"]),
            ("rtl", ["viewStart", "TextAlign", "right-to-left"]),
        ]

    def test_ключ_с_полностью_дублирующими_терминами_пропускается(self):
        aliases = {"dao": ["room"], "orm": ["room"]}
        assert expand_query_detailed("dao orm", aliases) == [("dao", ["room"])]


class TestCheckedInDictionary:
    def test_словарь_в_репозитории_заморожен(self):
        assert load_aliases() == ALIASES

    def test_битый_путь_даёт_пустой_словарь(self, tmp_path):
        assert load_aliases(tmp_path / "missing.json") == {}
