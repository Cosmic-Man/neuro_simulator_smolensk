from __future__ import annotations

import time
import tracemalloc
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import STATIC_DIR
from .scenarios import ScenarioConflictError
from .service import ProblemBService


class SimulateRequest(BaseModel):
    scenario: str = "inertial"
    mode: Literal["expert", "adapted"] | None = None
    horizon: int | None = Field(default=None, ge=1, le=20)
    impulses: dict[str, float] = Field(default_factory=dict)


class ScenarioPayload(BaseModel):
    version: int = 1
    id: str
    label: str
    description: str = ""
    mode: Literal["expert", "adapted"] = "adapted"
    horizon: int = Field(default=8, ge=1, le=20)
    impulses: dict[str, float] = Field(default_factory=dict)


tracemalloc.start()
_initialization_started = time.perf_counter()
service = ProblemBService()
INITIALIZATION_SECONDS = time.perf_counter() - _initialization_started
_, INITIALIZATION_PEAK_BYTES = tracemalloc.get_traced_memory()
tracemalloc.stop()
app = FastAPI(
    title="Нейросимулятор Смоленска — проблема Б",
    description="Объяснимая модель транспортной доступности и безопасности городской мобильности.",
    version="0.2.0-local",
)
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


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
        "problem": "Б",
        "periods": len(service.bundle.raw),
        "features": len(service.bundle.features.columns),
        "models_ready": True,
        "initialization_seconds": round(INITIALIZATION_SECONDS, 4),
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


@app.get("/api/fcm")
def fcm(mode: Literal["expert", "adapted"] = Query(default="adapted")) -> dict[str, object]:
    return service.fcm(mode)


@app.get("/api/evaluation")
def evaluation() -> dict[str, object]:
    return service.evaluation()


@app.get("/api/scenarios")
def scenarios() -> dict[str, object]:
    return {"scenarios": service.scenarios()}


@app.post("/api/scenarios", status_code=201)
def save_scenario(payload: ScenarioPayload) -> dict[str, object]:
    try:
        return service.save_scenario(payload.model_dump())
    except ScenarioConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/simulate")
def simulate(request: SimulateRequest) -> dict[str, object]:
    try:
        return service.simulate(
            scenario_id=request.scenario,
            mode=request.mode,
            horizon=request.horizon,
            custom_impulses=request.impulses,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
