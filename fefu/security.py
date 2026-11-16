"""Безопасность: CSRF, сессии, проверка данных, пароли, лимиты, заголовки."""
import hmac
import random
import re
import secrets
import time
import unicodedata
from functools import wraps
from urllib.parse import urlparse

from flask import abort, current_app, g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db

# ───────────────────────── запрос ─────────────────────────


def client_ip() -> str:
    return request.remote_addr or "0.0.0.0"


def wants_json() -> bool:
    return request.headers.get("X-Requested-With") == "fetch" or request.path.startswith("/api/")


def safe_next(url):
    """Разрешаем редирект только на путь внутри нашего сайта."""
    if not url or not isinstance(url, str):
        return None
    if not url.startswith("/") or url.startswith("//") or "\\" in url:
        return None
    parsed = urlparse(url)
    if parsed.scheme or parsed.netloc:
        return None
    return url


# ───────────────────────── CSRF ─────────────────────────


def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def _csrf_protect():
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
    expected = session.get("csrf", "")
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400, description="Форма устарела или подделана. Обновите страницу и повторите действие.")


# ───────────────────────── текущий пользователь ─────────────────────────


def _load_user():
    g.user = None
    uid = session.get("uid")
    if not uid:
        return
    row = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if row and row["is_active"] and row["session_version"] == session.get("sv"):
        g.user = row
    else:
        session.clear()


def login_user(user, remember: bool = False):
    """Открывает новую сессию. Старая очищается (защита от фиксации сессии)."""
    session.clear()
    session["uid"] = user["id"]
    session["sv"] = user["session_version"]
    session["csrf"] = secrets.token_urlsafe(32)
    session.permanent = bool(remember)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if wants_json():
                return jsonify(ok=False, error="Нужно войти в аккаунт.", login=url_for("auth.login")), 401
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


# ───────────────────────── заголовки ─────────────────────────

_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


def _security_headers(resp):
    resp.headers.setdefault("Content-Security-Policy", _CSP)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if current_app.config["IS_PRODUCTION"]:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    # Страницы с личными данными не должны возвращаться из кэша после выхода.
    if request.endpoint != "static":
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


def init_app(app):
    app.before_request(_load_user)
    app.before_request(_csrf_protect)
    app.after_request(_security_headers)


# ───────────────────────── проверка данных ─────────────────────────

_HOMOGLYPHS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
    "к": "k", "м": "m", "т": "t", "н": "h", "в": "b", "і": "i", "ѕ": "s", "ј": "j",
})


def normalize_username(raw: str) -> str:
    return unicodedata.normalize("NFKC", (raw or "").strip())


def username_key(username: str) -> str:
    """Ключ уникальности: «Админ», «админ» и «аdmin» не должны сосуществовать."""
    return unicodedata.normalize("NFKC", username).casefold().translate(_HOMOGLYPHS)


_USERNAME_RE = re.compile(r"^[\w.\-]{3,24}$")
_RESERVED = {
    username_key(w) for w in (
        "admin", "administrator", "root", "support", "moderator", "system", "fefu", "dvfu",
        "courier", "staff", "админ", "администратор", "модератор", "поддержка", "курьер",
        "тёмныйфефу", "темныйфефу", "деканат",
    )
}


def validate_username(username: str):
    if not _USERNAME_RE.match(username):
        return "От 3 до 24 символов: буквы, цифры, точка, дефис и подчёркивание."
    if username.isdigit():
        return "Имя не может состоять только из цифр."
    if username_key(username) in _RESERVED:
        return "Это имя зарезервировано. Придумайте другое."
    return None


_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$")


def validate_email(email: str):
    if len(email) > 254 or not _EMAIL_RE.match(email):
        return "Похоже, в адресе почты ошибка."
    return None


_COMMON_PASSWORDS = {
    "123456", "1234567", "12345678", "123456789", "1234567890", "password", "password1",
    "qwerty", "qwerty123", "qwertyuiop", "111111", "000000", "abc123", "iloveyou", "admin",
    "letmein", "welcome", "monkey", "dragon", "12341234", "11111111", "qazwsxedc",
    "йцукен", "пароль", "пароль123", "123456789a", "zachetka", "fefu2024", "fefu1234",
}


def validate_password(password: str, username: str = "", email: str = ""):
    if len(password) < 8:
        return "Пароль слишком короткий: нужно минимум 8 символов."
    if len(password) > 128:
        return "Пароль слишком длинный: максимум 128 символов."
    low = password.casefold()
    if low in _COMMON_PASSWORDS:
        return "Этот пароль взломают за 0,3 секунды. Придумайте другой."
    if len(username) >= 3 and username.casefold() in low:
        return "Не используйте имя пользователя внутри пароля."
    local = email.split("@")[0].casefold() if email else ""
    if len(local) >= 4 and local in low:
        return "Не используйте адрес почты внутри пароля."
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    if len(password) < 14 and not (has_letter and has_digit):
        return "Добавьте и буквы, и цифры — или сделайте пароль длиннее 14 символов."
    return None


# ───────────────────────── пароли ─────────────────────────

_dummy_hash = None


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(stored_hash, password: str) -> bool:
    """Если пользователя нет, всё равно считаем хеш — время ответа одинаково."""
    global _dummy_hash
    if stored_hash is None:
        if _dummy_hash is None:
            _dummy_hash = generate_password_hash(secrets.token_hex(8))
        check_password_hash(_dummy_hash, password)
        return False
    return check_password_hash(stored_hash, password)


# ───────────────────────── ограничение частоты ─────────────────────────


def rate_hit(db, key: str):
    db.execute("INSERT INTO rate_events(key, ts) VALUES (?, ?)", (key, time.time()))
    if random.random() < 0.02:
        _purge(db)


def rate_count(db, key: str, window: float) -> int:
    return db.execute(
        "SELECT COUNT(*) FROM rate_events WHERE key = ? AND ts > ?", (key, time.time() - window)
    ).fetchone()[0]


def rate_limited(db, key: str, limit: int, window: float) -> bool:
    return rate_count(db, key, window) >= limit


def too_many(message: str = "Слишком много попыток. Подождите немного."):
    abort(429, description=message)


def _purge(db):
    now = time.time()
    db.execute("DELETE FROM rate_events WHERE ts < ?", (now - 86400,))
    db.execute("DELETE FROM captchas WHERE expires_at < ?", (now,))
    db.execute("DELETE FROM password_resets WHERE expires_at < ?", (now - 7 * 86400,))
