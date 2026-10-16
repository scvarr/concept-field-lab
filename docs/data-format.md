# Формат данных

Текущий экспорт: `format="concept-field-permanent"`, `version=7`, `kind="graph"`, `exportedAt`, `state`, `historyEncoding="rfc6902-chain-v1"`, `history`; необязательный `importedHistory` сохраняет историю импортированных документов без вложенных архивов. v7 введён после удаления исторических полей определений и адаптеров; v1–v6 отклоняются. Демонстрационные экспорты не преобразуются.

`state` содержит четыре постоянных списка: `nodes`, `edges`, `designations`, `contextEdges`. Необязательные `sceneLab`, `thoughtLab` появляются при работе; внутренний `operatorVersion=5` обозначает существующий контракт подтверждений, а не версию файла.

| Запись | Основные поля и связи |
| --- | --- |
| Концепт | `id`, `structure: concept/alpha`, `label=""`, `designationOnly=true`, `kind`, `notes`, `origins`, конечные `x/y`; необязательные `operatorAlias`, `operatorRole`, `layoutPinned` |
| Ребро | `id`, `from/to` → концепты, `role: relation/component`, `type`; для нового параллельного отношения требуется `parallelReason` |
| Обозначение | `id`, `target` → концепт, `text`; необязательные источник/примечание |
| Разрешение | `id`, `from/to` → различные рёбра `relation`; направленная пара уникальна |
| Сцена | `id`, `label`, `kind: dialogue/knowledge`, `objects`, `entries`, `links` → ID сцен |
| Объект сцены | `id`, `conceptId`, `contentConceptId`, `label`, `displayNumber`; ссылки происхождения/применения |
| Вход сцены | `id`, `text`, `kind`, `assertions`, `retracts`; заполнение хранит `edgeId`, снимок `template`, локальные `from/to`, активацию и возможный `binding` |
| Рабочая копия | `id`, `sceneId`, `bundles`, `trace`; группа сохраняет источник и собственные объекты, заполнения и контексты |
| Разбор | `id`, `text`, `status`, `sceneId`, `config`, `selection`, `anchors`, `trace`; `config` содержит `nodes/edges/contexts`, локальные ID и постоянные ссылки |
| Конструкция | `id`, `label`, `version`, `config`; применение фиксирует версию и обязательный `contract` |

Содержательная привязка — использование обычного ребра: `binding=true`, локальные `from=to=id` одного элемента, постоянные концы соответствуют `conceptId → contentConceptId`. Оно сохраняет собственный ID и активацию, но не рисуется петлёй. `anchors` адресуют локальные ID и полуинтервалы Unicode-кодовых точек текста. `representation` хранит подтверждение с digest; ID, состав и границы валидируются сервером.

`sceneLab` хранит `currentSceneId`, а `thoughtLab` — `currentDraftId`, `drafts`, `templates`, `candidates`. Кандидат контекстного ребра не становится разрешением автоматически. Включение мысли в знания сохраняет происхождение и отображение исходных ID на независимые копии.

SQLite: `permanent_revisions(id,time,action,detail,state)` и `permanent_imports(fingerprint,time,document)`. Снимки кодируются JSON + zlib, запись — `BEGIN IMMEDIATE` с проверкой revision. Restore записывает новый снимок. JSON Patch разворачивается с проверкой порядка и совпадения последнего снимка с `state`.

Импорт добавляет точные ID, одинаковые объекты пропускает, конфликты отклоняет. Автоматического отождествления нет. База старого формата отклоняется до изменения; используйте новую SQLite. Исчерпывающие ограничения находятся в `validate_graph`, `validate_lab`, `validate_config` и `validate`; [контракт](contract.md) задаёт их смысл.
