"""Работа с SQLite: соединение на запрос, явные транзакции, схема."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import current_app, g

SCHEMA = Path(__file__).with_name("schema.sql")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(
            current_app.config["DATABASE"],
            timeout=10,
            isolation_level=None,  # автокоммит; транзакции открываем сами
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        # SQLite сравнивает без учёта регистра только латиницу, поэтому для
        # поиска по-русски нужна своя функция.
        conn.create_function(
            "casefold", 1,
            lambda s: s.casefold() if isinstance(s, str) else s,
            deterministic=True,
        )
        g.db = conn
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


@contextmanager
def transaction(db: sqlite3.Connection):
    """BEGIN IMMEDIATE ... COMMIT; при любом исключении откат."""
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except BaseException:
        db.execute("ROLLBACK")
        raise
    else:
        db.execute("COMMIT")


def init_db():
    db = get_db()
    db.executescript(SCHEMA.read_text(encoding="utf-8"))
    # Миграция баз, созданных до появления продавцов: добавляем недостающие столбцы.
    for table, col, ddl in (
        ("users", "is_seller", "INTEGER NOT NULL DEFAULT 0"),
        ("products", "seller_id", "INTEGER REFERENCES users(id) ON DELETE SET NULL"),
        ("products", "status", "TEXT NOT NULL DEFAULT 'approved'"),
        ("game_state", "daily_streak", "INTEGER NOT NULL DEFAULT 0"),
        ("game_state", "last_daily", "REAL NOT NULL DEFAULT 0"),
    ):
        if col not in {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def init_app(app):
    app.teardown_appcontext(close_db)
