from __future__ import annotations

import time
import tracemalloc
import uuid
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from .config import AUTO_CREATE_SCHEMA, SESSION_COOKIE_NAME, STATIC_DIR
from .database import create_schema, get_db
from .db_models import AuditLog, AuthSession, ScenarioShare, USER_ROLES, User, utcnow
from .scenarios import ScenarioConflictError, ScenarioNotFoundError, ScenarioStore, export_payload
from .security import (
    AuthContext,
    active_admin_count,
    authenticate,
    clear_session_cookie,
    create_user,
    get_auth_context,
    hash_password,
    issue_session,
    public_user,
    require_csrf,
    require_csrf_roles,
    require_roles,
    rotate_csrf_token,
    set_session_cookie,
    verify_password,
    write_audit,
)
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


class ScenarioSharingPayload(BaseModel):
    observer_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)


class LoginPayload(BaseModel):
    username: str
    password: str


class ChangePasswordPayload(BaseModel):
    current_password: str
    new_password: str


class UserCreatePayload(BaseModel):
    username: str
    display_name: str
    password: str
    role: Literal["observer", "user", "admin"] = "observer"
    must_change_password: bool = True


class UserUpdatePayload(BaseModel):
    display_name: str | None = None
    role: Literal["observer", "user", "admin"] | None = None
    is_active: bool | None = None


class ResetPasswordPayload(BaseModel):
    password: str
    must_change_password: bool = True


if AUTO_CREATE_SCHEMA:
    create_schema()

tracemalloc.start()
_initialization_started = time.perf_counter()
service = ProblemBService()
INITIALIZATION_SECONDS = time.perf_counter() - _initialization_started
_, INITIALIZATION_PEAK_BYTES = tracemalloc.get_traced_memory()
tracemalloc.stop()

app = FastAPI(
    title="Нейросимулятор Смоленска — проблема Б",
    description="Объяснимая модель транспортной доступности и безопасности городской мобильности.",
    version="0.3.0-demo-auth",
)
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

viewer_user = require_roles("observer", "user", "admin")
scenario_editor = require_csrf_roles("user", "admin")
scenario_sharing_viewer = require_roles("user", "admin")
admin_editor = require_csrf_roles("admin")
admin_viewer = require_roles("admin")


def scenario_error(error: Exception) -> HTTPException:
    if isinstance(error, ScenarioConflictError):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, ScenarioNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    return HTTPException(status_code=422, detail=str(error))


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/api/health")
def health(response: Response, db: Session = Depends(get_db)) -> dict[str, object]:
    database_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        database_status = "unavailable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if database_status == "ok" else "degraded",
        "database": database_status,
        "problem": "Б",
        "periods": len(service.bundle.raw),
        "features": len(service.bundle.features.columns),
        "models_ready": True,
        "initialization_seconds": round(INITIALIZATION_SECONDS, 4),
        "initialization_peak_mb": round(INITIALIZATION_PEAK_BYTES / 1024 / 1024, 2),
    }


@app.post("/api/auth/login")
def login(payload: LoginPayload, response: Response, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = authenticate(db, payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")
    _, session_token, csrf_token = issue_session(db, user)
    set_session_cookie(response, session_token)
    return {"user": public_user(user), "csrf_token": csrf_token}


@app.get("/api/auth/me")
def auth_me(context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    csrf_token = rotate_csrf_token(db, context.session)
    return {"user": public_user(context.user), "csrf_token": csrf_token}


@app.post("/api/auth/logout")
def logout(
    response: Response,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    context.session.revoked_at = utcnow()
    write_audit(db, "auth.logout", user_id=context.user.id)
    db.commit()
    clear_session_cookie(response)
    return {"ok": True}


@app.post("/api/auth/change-password")
def change_password(
    payload: ChangePasswordPayload,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    if not verify_password(payload.current_password, context.user.password_hash):
        raise HTTPException(status_code=422, detail="Текущий пароль указан неверно")
    try:
        context.user.password_hash = hash_password(payload.new_password)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    context.user.must_change_password = False
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == context.user.id, AuthSession.id != context.session.id)
        .values(revoked_at=utcnow())
    )
    write_audit(db, "auth.password_changed", user_id=context.user.id)
    db.commit()
    return {"ok": True}


@app.get("/api/metadata")
def metadata(_: User = Depends(viewer_user)) -> dict[str, object]:
    return service.metadata()


@app.get("/api/history")
def history(_: User = Depends(viewer_user)) -> dict[str, object]:
    return service.history()


@app.get("/api/indices")
def indices(_: User = Depends(viewer_user)) -> dict[str, object]:
    return service.indices()


@app.get("/api/fcm")
def fcm(
    mode: Literal["expert", "adapted"] = Query(default="adapted"),
    _: User = Depends(viewer_user),
) -> dict[str, object]:
    return service.fcm(mode)


@app.get("/api/evaluation")
def evaluation(_: User = Depends(viewer_user)) -> dict[str, object]:
    return service.evaluation()


@app.get("/api/scenarios")
def scenarios(user: User = Depends(viewer_user), db: Session = Depends(get_db)) -> dict[str, object]:
    return {"scenarios": ScenarioStore(db).list(user)}


@app.get("/api/scenarios/{reference}/shares")
def scenario_shares(
    reference: str,
    user: User = Depends(scenario_sharing_viewer),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return ScenarioStore(db).sharing(reference, user)
    except (ScenarioConflictError, ScenarioNotFoundError, ValueError) as error:
        raise scenario_error(error) from error


@app.put("/api/scenarios/{reference}/shares")
def update_scenario_shares(
    reference: str,
    payload: ScenarioSharingPayload,
    user: User = Depends(scenario_editor),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        sharing = ScenarioStore(db).set_sharing(reference, user, payload.observer_ids)
        write_audit(
            db,
            "scenario.sharing_updated",
            user_id=user.id,
            entity_type="scenario",
            entity_id=sharing["scenario"]["database_id"],
            details={"observer_ids": [str(observer_id) for observer_id in payload.observer_ids]},
        )
        db.commit()
        return sharing
    except (ScenarioConflictError, ScenarioNotFoundError, ValueError) as error:
        raise scenario_error(error) from error


@app.post("/api/scenarios", status_code=201)
def save_scenario(
    payload: ScenarioPayload,
    user: User = Depends(scenario_editor),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        saved = ScenarioStore(db).save(payload.model_dump(), user)
        write_audit(db, "scenario.created", user_id=user.id, entity_type="scenario", entity_id=saved["database_id"], details={"slug": saved["id"]})
        db.commit()
        return saved
    except (ScenarioConflictError, ValueError) as error:
        raise scenario_error(error) from error


@app.put("/api/scenarios/{reference}")
def update_scenario(
    reference: str,
    payload: ScenarioPayload,
    user: User = Depends(scenario_editor),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        saved = ScenarioStore(db).update(reference, payload.model_dump(), user)
        write_audit(db, "scenario.updated", user_id=user.id, entity_type="scenario", entity_id=saved["database_id"], details={"slug": saved["id"]})
        db.commit()
        return saved
    except (ScenarioConflictError, ScenarioNotFoundError, ValueError) as error:
        raise scenario_error(error) from error


@app.delete("/api/scenarios/{reference}")
def delete_scenario(
    reference: str,
    user: User = Depends(scenario_editor),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        deleted = ScenarioStore(db).delete(reference, user)
        write_audit(db, "scenario.deleted", user_id=user.id, entity_type="scenario", entity_id=deleted["database_id"], details={"slug": deleted["id"]})
        db.commit()
        return deleted
    except (ScenarioConflictError, ScenarioNotFoundError, ValueError) as error:
        raise scenario_error(error) from error


@app.get("/api/scenarios/{reference}/export")
def export_scenario(
    reference: str,
    user: User = Depends(viewer_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    try:
        scenario = ScenarioStore(db).get(reference, user)
    except (ScenarioConflictError, ScenarioNotFoundError, ValueError) as error:
        raise scenario_error(error) from error
    return JSONResponse(
        export_payload(scenario),
        headers={"Content-Disposition": f'attachment; filename="{scenario["id"]}.json"'},
    )


@app.post("/api/simulate")
def simulate(
    request: SimulateRequest,
    user: User = Depends(viewer_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        scenario = ScenarioStore(db).get(request.scenario, user)
        return service.simulate(
            scenario_id=scenario["id"],
            mode=request.mode,
            horizon=request.horizon,
            custom_impulses=request.impulses,
            scenario_payload=scenario,
        )
    except (ScenarioConflictError, ScenarioNotFoundError, ValueError) as error:
        raise scenario_error(error) from error


@app.get("/api/admin/users")
def admin_users(_: User = Depends(admin_viewer), db: Session = Depends(get_db)) -> dict[str, Any]:
    users = db.scalars(select(User).order_by(User.username)).all()
    return {"users": [public_user(user) for user in users], "roles": list(USER_ROLES)}


@app.post("/api/admin/users", status_code=201)
def admin_create_user(
    payload: UserCreatePayload,
    actor: User = Depends(admin_editor),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        user = create_user(db, **payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    write_audit(db, "user.created_by_admin", user_id=actor.id, entity_type="user", entity_id=str(user.id), details={"role": user.role})
    db.commit()
    return public_user(user)


@app.patch("/api/admin/users/{user_id}")
def admin_update_user(
    user_id: str,
    payload: UserUpdatePayload,
    actor: User = Depends(admin_editor),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        target = db.get(User, uuid.UUID(user_id))
    except (TypeError, ValueError):
        target = None
    if target is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    new_role = payload.role if payload.role is not None else target.role
    new_active = payload.is_active if payload.is_active is not None else target.is_active
    if target.role == "admin" and target.is_active and (new_role != "admin" or not new_active) and active_admin_count(db) <= 1:
        raise HTTPException(status_code=409, detail="Нельзя отключить или понизить последнего активного администратора")
    if payload.display_name is not None:
        display_name = payload.display_name.strip()
        if not 1 <= len(display_name) <= 120:
            raise HTTPException(status_code=422, detail="Отображаемое имя должно содержать 1–120 символов")
        target.display_name = display_name
    target.role = new_role
    target.is_active = new_active
    if target.role != "observer" or not target.is_active:
        db.execute(delete(ScenarioShare).where(ScenarioShare.observer_id == target.id))
    if not target.is_active:
        db.execute(update(AuthSession).where(AuthSession.user_id == target.id).values(revoked_at=utcnow()))
    write_audit(db, "user.updated", user_id=actor.id, entity_type="user", entity_id=str(target.id), details={"role": target.role, "is_active": target.is_active})
    db.commit()
    db.refresh(target)
    return public_user(target)


@app.post("/api/admin/users/{user_id}/reset-password")
def admin_reset_password(
    user_id: str,
    payload: ResetPasswordPayload,
    actor: User = Depends(admin_editor),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    try:
        target = db.get(User, uuid.UUID(user_id))
    except (TypeError, ValueError):
        target = None
    if target is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    try:
        target.password_hash = hash_password(payload.password)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    target.must_change_password = payload.must_change_password
    db.execute(update(AuthSession).where(AuthSession.user_id == target.id).values(revoked_at=utcnow()))
    write_audit(db, "user.password_reset", user_id=actor.id, entity_type="user", entity_id=str(target.id))
    db.commit()
    return {"ok": True}


@app.get("/api/admin/audit")
def admin_audit(
    _: User = Depends(admin_viewer),
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    records = db.scalars(
        select(AuditLog).options(joinedload(AuditLog.user)).order_by(AuditLog.created_at.desc()).limit(limit)
    ).all()
    return {
        "events": [
            {
                "id": str(record.id),
                "action": record.action,
                "entity_type": record.entity_type,
                "entity_id": record.entity_id,
                "details": record.details,
                "created_at": record.created_at.isoformat(),
                "user": public_user(record.user) if record.user else None,
            }
            for record in records
        ]
    }
