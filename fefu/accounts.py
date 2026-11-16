"""Создание и поиск пользователей (общая логика для сайта и командной строки)."""
import time

from flask import current_app

from . import wallet
from .db import transaction
from .security import hash_password, username_key


def create_user(db, username: str, email: str, password: str, role: str = "user") -> int:
    """Создаёт пользователя, стартовый баланс и игровое состояние. Бросает sqlite3.IntegrityError
    при дубликате имени или почты."""
    now = time.time()
    with transaction(db):
        cur = db.execute(
            "INSERT INTO users(username, username_key, email, password_hash, role, balance, created_at)"
            " VALUES (?,?,?,?,?,0,?)",
            (username, username_key(username), email.lower(), hash_password(password), role, now),
        )
        uid = cur.lastrowid
        wallet.apply(db, uid, current_app.config["START_BALANCE"], "signup_bonus", "Приветственные зачётки")
        db.execute("INSERT INTO game_state(user_id, last_collect) VALUES (?, ?)", (uid, now))
    return uid


def find_user(db, identifier: str):
    """Ищет по имени (без учёта регистра и похожих букв) или по почте."""
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    if "@" in identifier:
        return db.execute("SELECT * FROM users WHERE email = ?", (identifier.lower(),)).fetchone()
    return db.execute(
        "SELECT * FROM users WHERE username_key = ?", (username_key(identifier),)
    ).fetchone()


def user_by_id(db, uid: int):
    return db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
