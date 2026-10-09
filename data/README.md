# Источники данных

`sources.json` содержит immutable Git revision, URL, размер и SHA256 UD r2.17. `python scripts/fetch_ud.py` восстанавливает исходники в игнорируемом `raw/` и отказывается принимать несовпадение с сохранённым manifest.

SynTagRus: Computational Linguistics Laboratory, A.A. Kharkevich Institute of Information Transmission Problems, Russian Academy of Sciences; UD contributors Kira Droganova, Olga Lyashevskaya, Daniel Zeman. Лицензия исходных данных [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Производные извлечения и предсказания SynTagRus в `results/` распространяются на тех же условиях.

Russian GSD: UD contributors Ryan McDonald, Vitaly Nikolaev, Olga Lyashevskaya; аннотации [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). README источника отдельно оговаривает, что Google не владеет правами на исходное содержимое. Проект использует данные только для бесплатного некоммерческого исследования; результаты не содержат полных текстов статей.

Копии исходных LICENSE.txt и README.md сохраняются загрузчиком вместе с данными; ссылки на документацию — `docs/literature.md`. Механизм не использует готовые языковые модели.
