---
name: curator-update-docs
description: Выполняет semantic project write-back одобренного Memory Curator capture. Загружать только из curator-save после точного ответа status=update_project_docs и next_action=curator-update-docs.
---

# Curator Update Docs

## Входной барьер

Работай только с полным ответом `curator_capture_approve`, в котором точные
значения `status=update_project_docs` и `next_action=curator-update-docs`.
Используй `capture_id`, `base_dir`, `map_path` и `facts` прямо из этого ответа:
manifest неизменяем, состав и содержание фактов не пересобираются. Если барьер
не выполнен, остановись до чтения или изменения файлов.

## Процесс

1. Прочитай карту только по `map_path`. Не ищи другую карту и не меняй её.
2. До первой правки выполни preflight для всего `facts`. Для каждого факта:
   - сопоставь его с `watch_for` темы;
   - выбери `capture` (`knowledge`, `rules` или `records`) и target, чей список
     `captures` содержит этот capture;
   - примени `mode` и `instructions`, разреши target path/glob внутри `base_dir`
     и выбери один `canonical_file`;
   - прочитай нужные target-документы, чтобы выбрать каноническое место и их
     существующий формат;
   - заранее определи все файлы, которые требует синхронно изменить target.
3. Весь набор обязан иметь однозначные маршруты до редактирования. Если факт не
   совпал с темой или writable-target, совпал с несколькими маршрутами без
   однозначного выбора либо доступен только через `readonly`, останови весь
   набор без правок. Так же поступи при неразрешимом glob, пути вне `base_dir`
   или неоднозначном имени нового файла. Fallback-маршрута нет.
4. Примени минимальные смысловые патчи в локальном стиле и по `instructions`:
   `update` актуализирует существующее знание, `append` добавляет новую
   историческую запись без переписывания прежних. Не добавляй универсальный
   Curator block или служебные секции, если их не требует формат документа.
   Новый маршрут не создавай.
5. Проверь изменённые документы и выполни только короткую проверку, прямо
   требуемую `instructions`, если она есть. Для каждого факта подготовь ровно
   один placement: исходный `candidate_id`, выбранные `topic`, `target` и
   `capture`, root-relative `canonical_file` и непустой `changed_files` со всеми
   изменёнными файлами этого target; `changed_files` содержит `canonical_file`.
6. Без второго approval вызови `curator_capture_complete` один раз с исходным
   `capture_id` и всеми `placements`. Успех означает только ответ с точным
   `status=completed`; верни его без повторной сборки manifest.
