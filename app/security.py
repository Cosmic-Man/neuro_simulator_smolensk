from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from pwdlib import PasswordHash
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from .config import SESSION_COOKIE_NAME, SESSION_COOKIE_SECURE, SESSION_TTL_SECONDS
from .database import get_db
from .db_models import AuditLog, AuthSession, USER_ROLES, User, utcnow


USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
PASSWORD_HASH = PasswordHash.recommended()


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: AuthSession


def normalize_username(username: str) -> str:
    normalized = username.strip().lower()
    if not USERNAME_RE.fullmatch(normalized):
        raise ValueError("Логин должен содержать 3–64 латинских символа, цифры, '.', '_' или '-'")
    return normalized


def validate_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("Пароль должен содержать не менее 10 символов")
    if len(password) > 256:
        raise ValueError("Пароль не должен превышать 256 символов")
    return password


def hash_password(password: str) -> str:
    return PASSWORD_HASH.hash(validate_password(password))


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return PASSWORD_HASH.verify(password, password_hash)
    except (TypeError, ValueError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def public_user(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "created_at": user.created_at.isoformat(),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


def write_audit(
    db: Session,
    action: str,
    *,
    user_id: Any = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
        )
    )


def create_user(
    db: Session,
    *,
    username: str,
    display_name: str,
    password: str,
    role: str,
    must_change_password: bool = True,
) -> User:
    username = normalize_username(username)
    display_name = display_name.strip()
    if not 1 <= len(display_name) <= 120:
        raise ValueError("Отображаемое имя должно содержать 1–120 символов")
    if role not in USER_ROLES:
        raise ValueError(f"Неизвестная роль: {role}")
    if db.scalar(select(User.id).where(User.username == username)) is not None:
        raise ValueError("Пользователь с таким логином уже существует")
    user = User(
        username=username,
        display_name=display_name,
        password_hash=hash_password(password),
        role=role,
        must_change_password=must_change_password,
    )
    db.add(user)
    db.flush()
    write_audit(db, "user.created", user_id=user.id, entity_type="user", entity_id=str(user.id), details={"role": role})
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, username: str, password: str) -> User | None:
    normalized = username.strip().lower()
    user = db.scalar(select(User).where(User.username == normalized))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        write_audit(db, "auth.login_failed", user_id=user.id if user else None, details={"username": normalized})
        db.commit()
        return None
    user.last_login_at = utcnow()
    write_audit(db, "auth.login", user_id=user.id)
    db.commit()
    db.refresh(user)
    return user


def issue_session(db: Session, user: User) -> tuple[AuthSession, str, str]:
    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    record = AuthSession(
        token_hash=token_hash(session_token),
        csrf_token_hash=token_hash(csrf_token),
        user_id=user.id,
        expires_at=utcnow() + timedelta(seconds=SESSION_TTL_SECONDS),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record, session_token, csrf_token


def rotate_csrf_token(db: Session, session: AuthSession) -> str:
    csrf_token = secrets.token_urlsafe(32)
    session.csrf_token_hash = token_hash(csrf_token)
    db.commit()
    return csrf_token


def set_session_cookie(response: Any, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=SESSION_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Any) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


def _load_context(request: Request, db: Session) -> AuthContext:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется вход")
    record = db.scalar(
        select(AuthSession)
        .options(joinedload(AuthSession.user))
        .where(AuthSession.token_hash == token_hash(raw_token))
    )
    if (
        record is None
        or record.revoked_at is not None
        or record.expires_at <= utcnow()
        or not record.user.is_active
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Сессия недействительна или истекла")
    return AuthContext(record.user, record)


def get_auth_context(request: Request, db: Session = Depends(get_db)) -> AuthContext:
    return _load_context(request, db)


def require_roles(*roles: str):
    invalid = set(roles) - set(USER_ROLES)
    if invalid:
        raise ValueError(f"Неизвестные роли: {sorted(invalid)}")

    def dependency(context: AuthContext = Depends(get_auth_context)) -> User:
        if context.user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
        return context.user

    return dependency


def require_csrf(request: Request, context: AuthContext = Depends(get_auth_context)) -> AuthContext:
    supplied = request.headers.get("X-CSRF-Token", "")
    if not supplied or not hmac.compare_digest(token_hash(supplied), context.session.csrf_token_hash):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Проверка CSRF не пройдена")
    origin = request.headers.get("Origin")
    if origin:
        expected = f"{request.url.scheme}://{request.url.netloc}"
        if origin.rstrip("/") != expected.rstrip("/"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недопустимый источник запроса")
    return context


def require_csrf_roles(*roles: str):
    invalid = set(roles) - set(USER_ROLES)
    if invalid:
        raise ValueError(f"Неизвестные роли: {sorted(invalid)}")

    def dependency(context: AuthContext = Depends(require_csrf)) -> User:
        if context.user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
        return context.user

    return dependency


def active_admin_count(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))) or 0)
