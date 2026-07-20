# Локальный прототип по проблеме Б

Приложение объединяет квартальные данные 2006Q1–2025Q4, базовые прогнозные модели, нечёткую когнитивную карту (FCM) и три компактные ANFIS-модели.

## Реализовано

- пять релевантных муниципальных программ из Excel;
- train 2006Q1–2018Q4, validation 2019Q1–2022Q4, test 2023Q1–2025Q4;
- Seasonal Naive, Ridge по четырём лагам, экспертная и адаптированная FCM, ANFIS;
- 17 узлов и 37 причинных связей, веса `0.70 × экспертные + 0.30 × данные`;
- семь сценариев, чувствительность факторов и текстовое объяснение;
- FastAPI и одностраничный интерфейс с Plotly.js и Cytoscape.js.

## Запуск

### Через виртуальное окружение `.venv`

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

При повторном запуске достаточно активировать уже созданное окружение и запустить сервер:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Чтобы выйти из виртуального окружения, выполните `deactivate`.

### Через готовые PowerShell-скрипты

```powershell
Set-Location "D:\Codex_code\Summer School\neuro_simulator_smolensk"
.\setup_local.ps1
.\run_local.ps1
```

Открыть `http://127.0.0.1:8000`. Документация API: `http://127.0.0.1:8000/docs`.

## Тесты

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Все границы нормализации определяются только по обучающему периоду. Валидационные и тестовые значения преобразуются теми же параметрами.

## Связанный проект
- [graph_summer_school](https://github.com/Denhin-ii/graph_summer_school)
- [Summer_school_collab](https://github.com/Denhin-ii/Summer_school_collab)
