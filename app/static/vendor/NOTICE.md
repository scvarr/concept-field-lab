# Локальные библиотеки раскладки

Скачаны 12 октября 2026, используются Worker без обращения к сети. Файлы распределения сохранены без изменений; установка npm для работы приложения не требуется.

| Файл | Версия / исходный адрес | SHA256 |
|---|---|---|
| d3-7.9.0.min.js | [D3 7.9.0](https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js), [исходники](https://github.com/d3/d3/tree/v7.9.0) | f2094bbf6141b359722c4fe454eb6c4b0f0e42cc10cc7af921fc158fceb86539 |
| dagre-1.1.5.min.js | [Dagre 1.1.5](https://cdn.jsdelivr.net/npm/@dagrejs/dagre@1.1.5/dist/dagre.min.js), [исходники](https://github.com/dagrejs/dagre/tree/v1.1.5) | 072c8b304372ca2ea7e30e4811f071ddec36557e2f13758650c98a723acca420 |

D3 распространяется по ISC (`D3-LICENSE`). Dagre — MIT (`DAGRE-LICENSE`); bundle включает @dagrejs/graphlib 2.2.4 с MIT (`GRAPHLIB-LICENSE`). Полный D3 bundle выбран как готовое автономное UMD-распределение; приложение использует только force-функции. Лицензии и комментарии авторов сохранены.
