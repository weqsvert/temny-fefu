"""Журнал событий: и в базе (для админки и личного кабинета), и в файл."""
import time

from flask import current_app, request

from .db import get_db

# События, которые пользователь видит в своём журнале безопасности.
SECURITY_EVENTS = (
    "register", "login_success", "login_failed", "login_blocked", "account_locked", "logout",
    "password_changed", "password_reset_requested", "password_reset_done", "email_changed",
    "logout_everywhere",
)

EVENT_LABELS = {
    "register": "Регистрация",
    "login_success": "Вход выполнен",
    "login_failed": "Неудачная попытка входа",
    "login_blocked": "Вход отклонён: аккаунт временно заблокирован",
    "account_locked": "Аккаунт временно заблокирован из-за ошибок входа",
    "logout": "Выход",
    "password_changed": "Пароль изменён",
    "password_reset_requested": "Запрошен сброс пароля",
    "password_reset_done": "Пароль сброшен по ссылке",
    "email_changed": "Адрес почты изменён",
    "logout_everywhere": "Выход со всех устройств",
}


def log_event(event: str, user=None, details: str = "", username: str | None = None, user_id: int | None = None):
    """Пишет событие. Пароли и токены сюда передавать нельзя."""
    uid = user_id if user_id is not None else (user["id"] if user else None)
    name = username if username is not None else (user["username"] if user else None)
    ip = request.remote_addr if request else None
    ua = (request.headers.get("User-Agent", "") if request else "")[:200]
    details = (details or "")[:300]
    get_db().execute(
        "INSERT INTO audit_log(ts, user_id, username, event, ip, user_agent, details) VALUES (?,?,?,?,?,?,?)",
        (time.time(), uid, name, event, ip, ua, details),
    )
    current_app.logger.info("audit event=%s user=%s ip=%s %s", event, name or "-", ip, details)
