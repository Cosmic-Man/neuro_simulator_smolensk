from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import STATIC_DIR
from .service import ProblemBService


class SimulateRequest(BaseModel):
    scenario: str = "inertial"
    mode: Literal["expert", "adapted"] = "adapted"
    horizon: int = Field(default=8, ge=1, le=20)
    impulses: dict[str, float] = Field(default_factory=dict)


service = ProblemBService()
app = FastAPI(
    title="Нейросимулятор Смоленска — проблема Б",
    description="Локальный аналитический прототип транспортной доступности и безопасности.",
    version="0.1.0-local",
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
        "problem": "B",
        "periods": len(service.bundle.raw),
        "models_ready": True,
    }


@app.get("/api/metadata")
def metadata() -> dict[str, object]:
    return service.metadata()


@app.get("/api/history")
def history() -> dict[str, object]:
    return service.history()


@app.get("/api/fcm")
def fcm(mode: Literal["expert", "adapted"] = Query(default="adapted")) -> dict[str, object]:
    return service.fcm(mode)


@app.get("/api/evaluation")
def evaluation() -> dict[str, object]:
    return service.evaluation()


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

