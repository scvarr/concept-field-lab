# Источники данных

`sources.json` содержит immutable Git revision, URL, размер и SHA256 UD r2.17. `python scripts/fetch_ud.py` восстанавливает исходники в игнорируемом `raw/` и отказывается принимать несовпадение с сохранённым manifest.

SynTagRus: Computational Linguistics Laboratory, A.A. Kharkevich Institute of Information Transmission Problems, Russian Academy of Sciences; UD contributors Kira Droganova, Olga Lyashevskaya, Daniel Zeman. Лицензия исходных данных [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Производные извлечения и предсказания SynTagRus в `results/` распространяются на тех же условиях.

Russian GSD: UD contributors Ryan McDonald, Vitaly Nikolaev, Olga Lyashevskaya; аннотации [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). README источника отдельно оговаривает, что Google не владеет правами на исходное содержимое. Проект использует данные только для бесплатного некоммерческого исследования; результаты не содержат полных текстов статей.

Копии исходных LICENSE.txt и README.md сохраняются загрузчиком вместе с данными; ссылки на документацию — `docs/literature.md`. Механизм не использует готовые языковые модели.

Для шага 004 `parser-sources.json` фиксирует UDPipe russian-syntagrus UD 2.5 191206 и исторические r2.5 train/dev для аудита пересечения. Parser создан Institute of Formal and Applied Linguistics, Charles University (Milan Straka, Jana Straková и соавторы); библиотека MPL 2.0, модель CC BY-NC-SA 4.0. Immutable Git mirror модели указан в manifest; [оригинальная документация](https://ufal.mff.cuni.cz/udpipe/1/models). Команда загрузки `python scripts/fetch_parser.py`. Модель выполняет только предварительный морфосинтаксис, не приобретение наших правил.

Для шага 005 `external-sources.json` фиксирует Russian Taiga r2.17 test. School of Linguistics, HSE; contributors Olga Lyashevskaya, Olga Rudina, Natalia Vlasova, Anna Zhuravleva; исходные коллекции Taiga, MorphoRuEval-2017, GramEval-2020. Лицензия CC BY-SA 4.0. Производные `results/005/` распространяются на тех же условиях. Загрузка `python scripts/prepare_external_audit.py`. Оценки `annotations.json` выполнены вспомогательной LLM Codex, не независимым человеком, не являются обучающими данными операторов и не заменяют исходную ручную UD-разметку.
