<!-- route-catalog-marker: rp05-1f0c4b7e-93d2-45a8-8e6b-71c2ad9f04d3 -->

# Каталог маршрутов базы знаний

Маршрут = указатель на source-файл с правилом. При совпадении условий
(When to use) открой файл из Source и примени правило.

## Coroutines/DAO

**Description:** когда оборачивать вызовы в withContext, а когда нет

**When to use:**
- пишешь suspend-функцию поверх DAO;
- видишь withContext вокруг suspend-вызова.

**Source:** `kb/F72-withcontext-suspend-dao.md`

## Retrofit

**Description:** пути API-методов не дублируют префикс base URL

**When to use:**
- добавляешь API-метод в Retrofit-интерфейс.

**Source:** `kb/F109-retrofit-path-prefix.md`

## Dagger/ViewModelFactory

**Description:** контрибуции в ViewModelFactory-карту требуют @IntoMap + ключ

**When to use:**
- runtime-падение Unknown ViewModel;
- работаешь с ViewModelFactory и multibindings.

**Source:** `kb/F121-dagger-intomap.md`

## Валидация входа

**Description:** обязательные значения не маскируются заглушками

**When to use:**
- ревью конструктора экрана;
- аргумент приходит из route pattern (detail/{id}).

**Source:** `kb/F86-required-fields-no-orempty.md`

## Compose/RTL

**Description:** порт XML-выравнивания на Compose без явного TextAlign

**When to use:**
- переносишь TextView/XML-layout на Compose;
- выравнивание в LTR/RTL.

**Source:** `kb/F68-textalign-viewstart-port.md`

## Compose/modifier

**Description:** входной modifier один раз на корне composable

**When to use:**
- пишешь composable-экран с входным modifier;
- инсеты/фон приходят извне.

**Source:** `kb/F6-modifier-root-compose.md`
