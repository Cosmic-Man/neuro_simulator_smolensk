from __future__ import annotations

import time
import tracemalloc
from threading import RLock
from typing import Literal

from fastapi import Body, FastAPI, HTTPException, Query, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import STATIC_DIR
from .data import load_problem_b_data
from .datasets import DatasetStore
from .scenarios import export_payload, get_builtin, validate_scenario
from .service import ProblemBService


class ScenarioPayload(BaseModel):
    version: int = 1
    id: str
    label: str
    description: str = ""
    mode: Literal["expert", "adapted"] = "adapted"
    horizon: int = Field(default=8, ge=1, le=20)
    impulses: dict[str, float] = Field(default_factory=dict)


class SimulateRequest(BaseModel):
    scenario: str = "inertial"
    scenario_payload: ScenarioPayload | None = None
    mode: Literal["expert", "adapted"] | None = None
    horizon: int | None = Field(default=None, ge=1, le=20)
    impulses: dict[str, float] = Field(default_factory=dict)
    index_values: dict[str, float] = Field(default_factory=dict)


class DatasetSelectPayload(BaseModel):
    name: str


class DatasetRowPayload(BaseModel):
    values: dict[str, float]


tracemalloc.start()
_initialization_started = time.perf_counter()
service = ProblemBService()
dataset_store = DatasetStore()
service_lock = RLock()
INITIALIZATION_SECONDS = time.perf_counter() - _initialization_started
_, INITIALIZATION_PEAK_BYTES = tracemalloc.get_traced_memory()
tracemalloc.stop()

app = FastAPI(
    title="Нейросимулятор Смоленска — проблема Б",
    description="Локальная XLSX-версия без авторизации и базы данных.",
    version="0.5.0-local-xlsx",
)
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


def dataset_error(error: Exception) -> HTTPException:
    if isinstance(error, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    return HTTPException(status_code=422, detail=str(error))


def scenario_error(error: Exception) -> HTTPException:
    message = str(error)
    return HTTPException(status_code=404 if "Неизвестный сценарий" in message else 422, detail=message)


def rebuild_service(path, *, force_retrain: bool = False) -> ProblemBService:
    return ProblemBService(
        bundle=load_problem_b_data(path),
        model_dir=service.model_dir,
        force_retrain=force_retrain,
    )


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "storage": "xlsx",
        "dataset": service.bundle.source_path.name,
        "periods": len(service.bundle.raw),
        "initialization_seconds": round(INITIALIZATION_SECONDS, 3),
        "initialization_peak_mb": round(INITIALIZATION_PEAK_BYTES / 1024 / 1024, 2),
    }


@app.get("/api/metadata")
def metadata() -> dict[str, object]:
    return service.metadata()


@app.get("/api/history")
def history() -> dict[str, object]:
    return service.history()


@app.get("/api/indices")
def indices() -> dict[str, object]:
    return service.indices()


@app.get("/api/analysis")
def analysis() -> dict[str, object]:
    return service.analysis()


@app.get("/api/models/status")
def model_status() -> dict[str, object]:
    return service.training_status(dataset_store.path(service.bundle.source_path.name))


@app.post("/api/models/retrain")
def retrain_models() -> dict[str, object]:
    global service
    active_name = service.bundle.source_path.name
    active_path = dataset_store.path(active_name)
    latest = dataset_store.read(active_name)["rows_data"][-1]
    if all(abs(float(value)) < 1e-12 for value in latest["values"].values()):
        raise HTTPException(
            status_code=422,
            detail="Последний квартал заполнен только нулями. Внесите фактические значения перед переобучением.",
        )
    try:
        with service_lock:
            service = rebuild_service(active_path, force_retrain=True)
        return service.training_status(active_path)
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        raise dataset_error(error) from error


@app.get("/api/datasets")
def datasets() -> dict[str, object]:
    return dataset_store.catalog(service.bundle.source_path.name)


@app.get("/api/datasets/{name}")
def dataset_detail(name: str) -> dict[str, object]:
    try:
        return dataset_store.read(name)
    except (FileNotFoundError, ValueError) as error:
        raise dataset_error(error) from error


@app.post("/api/datasets/select")
def select_dataset(payload: DatasetSelectPayload) -> dict[str, object]:
    global service
    try:
        with service_lock:
            service = rebuild_service(dataset_store.path(payload.name))
        return dataset_store.catalog(service.bundle.source_path.name)
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        raise dataset_error(error) from error


@app.post("/api/datasets/upload", status_code=status.HTTP_201_CREATED)
def upload_dataset(
    name: str = Query(..., min_length=1, max_length=180),
    content: bytes = Body(..., media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
) -> dict[str, object]:
    global service
    try:
        with service_lock:
            saved_name = dataset_store.import_xlsx(name, content, load_problem_b_data)
            service = rebuild_service(dataset_store.path(saved_name))
        return {
            "name": saved_name,
            "catalog": dataset_store.catalog(saved_name),
        }
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        raise dataset_error(error) from error


@app.post("/api/datasets/{name}/rows", status_code=status.HTTP_201_CREATED)
def append_dataset_row(name: str, payload: DatasetRowPayload) -> dict[str, object]:
    try:
        with service_lock:
            period = dataset_store.append_row(name, payload.values, load_problem_b_data)
        active_name = service.bundle.source_path.name
        return {
            "dataset": dataset_store.read(name),
            "active": active_name,
            "period": period,
            "model_status": service.training_status(dataset_store.path(active_name)),
        }
    except (FileNotFoundError, OSError, ValueError) as error:
        raise dataset_error(error) from error


@app.put("/api/datasets/{name}/rows/{period}")
def update_dataset_row(name: str, period: str, payload: DatasetRowPayload) -> dict[str, object]:
    try:
        with service_lock:
            updated_period = dataset_store.update_row(name, period, payload.values, load_problem_b_data)
        active_name = service.bundle.source_path.name
        return {
            "dataset": dataset_store.read(name),
            "active": active_name,
            "period": updated_period,
            "model_status": service.training_status(dataset_store.path(active_name)),
        }
    except (FileNotFoundError, OSError, ValueError) as error:
        raise dataset_error(error) from error


@app.get("/api/fcm")
def fcm(mode: Literal["expert", "adapted"] = Query(default="adapted")) -> dict[str, object]:
    return service.fcm(mode)


@app.get("/api/evaluation")
def evaluation() -> dict[str, object]:
    return service.evaluation()


@app.get("/api/scenarios")
def scenarios() -> dict[str, object]:
    return {"scenarios": service.scenarios()}


@app.post("/api/scenarios/validate")
def validate_scenario_payload(payload: ScenarioPayload) -> dict[str, object]:
    try:
        return validate_scenario(payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/scenarios/{reference}/export")
def export_scenario(reference: str) -> JSONResponse:
    scenario = get_builtin(reference)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Неизвестный встроенный сценарий")
    return JSONResponse(
        export_payload(scenario),
        headers={"Content-Disposition": f'attachment; filename="{scenario["id"]}.json"'},
    )


@app.post("/api/simulate")
def simulate(request: SimulateRequest) -> dict[str, object]:
    scenario_payload = request.scenario_payload.model_dump() if request.scenario_payload else None
    try:
        return service.simulate(
            scenario_id=request.scenario,
            mode=request.mode,
            horizon=request.horizon,
            custom_impulses=request.impulses,
            index_values=request.index_values,
            scenario_payload=scenario_payload,
        )
    except ValueError as error:
        raise scenario_error(error) from error
