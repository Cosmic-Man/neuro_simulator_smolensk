# neuro_simulator_smolensk

## Установка

Создайте виртуальное окружение в папке проекта:

```powershell
python -m venv .venv
```

Активируйте его в PowerShell и установите зависимости:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Запустите JupyterLab только на локальном интерфейсе:

```powershell
python -m jupyter lab --ServerApp.ip=127.0.0.1 --ServerApp.port=8888
```

После запуска откройте [http://localhost:8888/]


## Related projects

- [graph_summer_school](https://github.com/Denhin-ii/graph_summer_school)
