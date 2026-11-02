# Путь к миллиону — Streamlit

Трекер трат и накоплений: цель 1 000 000 ₽, 25% с дохода + остаток, кешбеки в накопления, анализ по дням/неделям/месяцам, группы затрат.

## Запуск локально
    pip install -r requirements.txt
    streamlit run app.py

## Деплой (через Colab → GitHub → Streamlit Cloud)
1. Открой `upload_to_github.ipynb` в Colab, выполни ячейки — проект и репозиторий данных окажутся на GitHub.
2. На https://share.streamlit.io → New app → выбери репозиторий, файл `app.py`.
3. В Advanced settings → Secrets вставь содержимое из `.streamlit/secrets.toml.example` (его же выведет ноутбук).
Данные хранятся в приватном репозитории `million-data`, поэтому синхронизируются между телефоном и компьютером.
