from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import select

from .config import SCENARIO_DIR
from .database import SessionLocal
from .db_models import User
from .scenarios import ScenarioConflictError, ScenarioStore
from .security import create_user


DEMO_USERS = (
    ("observer", "Демонстрационный наблюдатель", "observer", "DEMO_OBSERVER_PASSWORD"),
    ("user", "Демонстрационный пользователь", "user", "DEMO_USER_PASSWORD"),
    ("admin", "Администратор", "admin", "DEMO_ADMIN_PASSWORD"),
)


def seed_demo_users() -> int:
    missing = [variable for *_, variable in DEMO_USERS if not os.getenv(variable)]
    if missing:
        raise SystemExit(f"Не заданы переменные окружения: {', '.join(missing)}")
    created = 0
    with SessionLocal() as db:
        for username, display_name, role, password_variable in DEMO_USERS:
            if db.scalar(select(User.id).where(User.username == username)) is not None:
                print(f"Пользователь {username}: уже существует")
                continue
            create_user(
                db,
                username=username,
                display_name=display_name,
                password=os.environ[password_variable],
                role=role,
                must_change_password=False,
            )
            created += 1
            print(f"Пользователь {username}: создан с ролью {role}")
    return created


def create_admin(username: str, display_name: str, password: str) -> None:
    with SessionLocal() as db:
        user = create_user(
            db,
            username=username,
            display_name=display_name,
            password=password,
            role="admin",
            must_change_password=False,
        )
        print(f"Администратор {user.username} создан")


def import_scenarios(owner_username: str, directory: Path) -> tuple[int, int]:
    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.username == owner_username.strip().lower()))
        if owner is None:
            raise SystemExit(f"Пользователь {owner_username} не найден")
        imported = 0
        skipped = 0
        store = ScenarioStore(db)
        for path in sorted(directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                store.save(payload, owner)
            except (OSError, json.JSONDecodeError, TypeError, ValueError, ScenarioConflictError) as error:
                skipped += 1
                print(f"{path.name}: пропущен ({error})")
            else:
                imported += 1
                print(f"{path.name}: импортирован")
        return imported, skipped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Управление демонстрационным нейросимулятором")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("seed-demo-users", help="Создать observer, user и admin из переменных окружения")

    admin_parser = commands.add_parser("create-admin", help="Создать администратора")
    admin_parser.add_argument("--username", required=True)
    admin_parser.add_argument("--display-name", required=True)
    admin_parser.add_argument("--password", default=os.getenv("DEMO_ADMIN_PASSWORD"))

    import_parser = commands.add_parser("import-scenarios", help="Импортировать runtime/scenarios в PostgreSQL")
    import_parser.add_argument("--owner", required=True)
    import_parser.add_argument("--directory", type=Path, default=SCENARIO_DIR)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "seed-demo-users":
        created = seed_demo_users()
        print(f"Создано пользователей: {created}")
        return
    if args.command == "create-admin":
        if not args.password:
            raise SystemExit("Передайте --password или задайте DEMO_ADMIN_PASSWORD")
        create_admin(args.username, args.display_name, args.password)
        return
    if args.command == "import-scenarios":
        imported, skipped = import_scenarios(args.owner, args.directory)
        print(f"Импортировано: {imported}; пропущено: {skipped}")


if __name__ == "__main__":
    main()
