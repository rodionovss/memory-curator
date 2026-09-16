---
status: draft
categories: [knowledge, rules, records]
modes: [update, append, readonly]
on_unmatched: report

topics:
  - name: navigation-and-source-authority
    watch_for: >-
      Меняется состав документации, её границы, канонический источник факта или
      правило разрешения расхождений между living docs, кодом и тестами.
    targets:
      - path: example/backend/docs/README.md
        captures: [knowledge, rules]
        mode: update
        instructions: >-
          Поддерживай индекс и таблицу источников истины. Не дублируй точные
          машинные контракты: направляй к DTO, validation, contract tests,
          migrations, repository schemas/queries и typed config.

  - name: system-architecture-and-runtime-flows
    watch_for: >-
      Меняются назначение backend, границы слоёв, точки входа, хранилища,
      внешние системы, фоновые потоки или их runtime-гарантии.
    targets:
      - path: example/backend/docs/architecture/overview.md
        captures: [knowledge, rules]
        mode: update
        instructions: >-
          Описывай текущее реализованное состояние и связывай детальные domain
          и integration docs; точный перечень endpoint, cron и конфигурацию
          оставляй их машинным источникам.

  - name: domain-behavior-and-invariants
    watch_for: >-
      Появляется или меняется устойчивое бизнес-поведение, термин, инвариант,
      источник данных, риск, согласованность или наблюдаемость доменного
      сценария.
    targets:
      - path: example/backend/docs/domains/*.md
        captures: [knowledge, rules]
        mode: update
        instructions: >-
          Создавай или обновляй документ затронутого домена после реализации.
          Фиксируй границы, инварианты и ссылки на код; не превращай документ
          в каталог классов и не записывай туда проектное намерение.
      - path: example/backend/CONTEXT.md
        captures: [knowledge, rules]
        mode: update
        instructions: >-
          Если файл существует или появился реальный терминологический выбор,
          веди только канонические термины и запрещённые синонимы. Не используй
          glossary как spec или описание реализации.

  - name: mobile-and-external-integration-contracts
    watch_for: >-
      Меняется поддерживаемый потребительский HTTP/payload-контракт, identity
      mapping, событие аналитики, внешний вызов, failure semantics, retry или
      compatibility boundary мобильной либо внешней интеграции.
    targets:
      - path: example/backend/docs/integrations/*.md
        captures: [knowledge, rules]
        mode: update
        instructions: >-
          Поддерживай человекочитаемую проекцию действующего контракта после
          реализации. Один канонический факт хранится в одном документе, а
          связанные flows ссылаются на него; точные transport/provider
          контракты сверяй с DTO, validation, providers и contract tests.

  - name: engineering-standards-and-evidence
    watch_for: >-
      Меняется обязательное инженерное правило, его область действия,
      механическая проверка, evidence либо routing правил для изменяемых
      файлов.
    targets:
      - path: example/backend/docs/engineering/README.md
        captures: [rules]
        mode: update
        instructions: >-
          Обновляй registry, маршрутизацию и metadata правила вместе с
          тематическим документом; неизвестная область действия является
          blocking condition.
      - path: example/backend/docs/engineering/{architecture-and-layers,code-style,contracts-and-data,reliability-and-observability,testing}.md
        captures: [rules]
        mode: update
        instructions: >-
          Изменяй каноническое требование, scope, статус и способ проверки в
          тематическом документе. Механический контракт ESLint, tests и code
          остаётся источником точных проверяемых деталей.

  - name: delivery-and-local-work-tracking
    watch_for: >-
      Меняется pipeline выполнения задач, критерии завершения, формат local
      spec/ticket, triage vocabulary либо правила владения domain knowledge.
    targets:
      - path: example/backend/docs/agents/*.md
        captures: [rules]
        mode: update
        instructions: >-
          Обновляй project adapter и инструкции tracker/domain/triage. Текущие
          требования задачи хранятся в подтверждённом brief или .scratch, а не
          в исторических документах docs/superpowers.

  - name: operations-and-environment-safety
    watch_for: >-
      Меняются семантика окружений, порядок эксплуатационной диагностики,
      правила доступа к stage/prod, источники логов или требования к секретам.
    targets:
      - path: example/backend/docs/operations/*.md
        captures: [knowledge, rules]
        mode: update
        instructions: >-
          Поддерживай безопасный эксплуатационный порядок и значения
          окружений; не записывай credentials, токены, ключи и иные секреты.

  - name: durable-architecture-decisions
    watch_for: >-
      Принято труднообратимое архитектурное решение после выбора между
      реальными альтернативами, без которого будущее изменение может ошибочно
      отменить решение.
    targets:
      - path: example/backend/docs/adr/[0-9][0-9][0-9][0-9]-*.md
        captures: [records, rules]
        mode: append
        instructions: >-
          Создавай следующий нумерованный ADR по правилам docs/adr/README.md;
          этот append-маршрут не включает README. Принятый ADR не переписывай,
          а при замене создай новый и пометь старый superseded.
      - path: example/backend/docs/adr/README.md
        captures: [rules]
        mode: update
        instructions: >-
          Поддерживай критерии и шаблон ADR, не используя ADR для локальных
          рефакторингов и простых endpoint.

  - name: historical-task-artifacts
    watch_for: >-
      Нужно восстановить прошлые требования, план, аудит или дату решения, но
      не изменить описание текущей системы.
    targets:
      - path: example/backend/docs/superpowers/{specs,plans,audits}/*.md
        captures: [records]
        mode: readonly
        instructions: >-
          Используй только как исторический контекст и только по прямому
          указанию пользователя. Не выбирай автоматически как активную spec и
          не обновляй вместо living docs.

  - name: exact-machine-contracts-without-document-route
    watch_for: >-
      Найдено новое точное HTTP, SQL, provider, migration или runtime-config
      знание, для которого нет устойчивого объяснения в подходящем living doc.
    targets: []
---

# Карта документации example/backend

Начинать с `example/backend/docs/README.md`, затем открывать только тему
затронутого изменения. Карта отделяет living docs (`update`) от неизменяемой
истории (`readonly`) и ADR, где сохраняется последовательность решений
(`append`).

Непокрытый маршрут: точные машинные контракты остаются в коде и тестах. Если
такое знание существенно для будущих сессий, но не укладывается в architecture,
domain, integration, operations или engineering topic, его нужно явно сообщить,
а не создавать дублирующую документацию без согласования.
