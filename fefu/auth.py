"""Регистрация, вход, выход, восстановление пароля."""
import hashlib
import math
import secrets
import sqlite3
import time

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template,
                   request, url_for)

from . import captcha, mailer
from .accounts import create_user, find_user, user_by_id
from .audit import log_event
from .db import get_db
from .security import (client_ip, hash_password, login_user, normalize_username, rate_count,
                       rate_hit, rate_limited, safe_next, too_many, validate_email,
                       validate_password, validate_username, verify_password, username_key)

bp = Blueprint("auth", __name__)

CAPTCHA_ERROR = "Ответ с проверки неверный. Мы выдали новую."


def _captcha_kind() -> str:
    return "question" if request.values.get("captcha_kind") == "question" else "image"


def _fresh_captcha(db):
    return captcha.new_captcha(db, _captcha_kind())


def _check_captcha(db) -> bool:
    return captcha.verify(db, request.form.get("captcha_id"), request.form.get("captcha_answer"))


# ───────────────────────── регистрация ─────────────────────────


@bp.route("/register", methods=("GET", "POST"))
def register():
    if g.user:
        return redirect(url_for("shop.index"))
    db = get_db()
    form, errors = {"username": "", "email": ""}, {}

    if request.method == "POST":
        ip = client_ip()
        if rate_limited(db, f"register:{ip}", 8, 3600):
            too_many("Слишком много регистраций с вашего адреса. Попробуйте через час.")
        rate_hit(db, f"register:{ip}")

        username = normalize_username(request.form.get("username"))
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""
        form = {"username": username, "email": email}

        if not _check_captcha(db):
            errors["captcha"] = CAPTCHA_ERROR
        if msg := validate_username(username):
            errors["username"] = msg
        if msg := validate_email(email):
            errors["email"] = msg
        if msg := validate_password(password, username, email):
            errors["password"] = msg
        elif password != password2:
            errors["password2"] = "Пароли не совпадают."
        if not request.form.get("accept"):
            errors["accept"] = "Нужно подтвердить, что вы понимаете: зачётки вымышлены."

        if "username" not in errors and db.execute(
            "SELECT 1 FROM users WHERE username_key = ?", (username_key(username),)
        ).fetchone():
            errors["username"] = "Это имя уже занято."
        if "email" not in errors and db.execute(
            "SELECT 1 FROM users WHERE email = ?", (email,)
        ).fetchone():
            errors["email"] = "Эта почта уже зарегистрирована. Если это вы — войдите или восстановите пароль."

        if not errors:
            try:
                uid = create_user(db, username, email, password)
            except sqlite3.IntegrityError:  # гонка двух регистраций
                errors["username"] = "Имя или почта уже заняты."
            else:
                user = user_by_id(db, uid)
                login_user(user)
                log_event("register", user=user)
                flash(f"Аккаунт создан. На баланс зачислено {current_app.config['START_BALANCE']} зачёток.", "ok")
                return redirect(url_for("shop.index"))

    return render_template("auth/register.html", form=form, errors=errors,
                           captcha=_fresh_captcha(db))


# ───────────────────────── вход / выход ─────────────────────────


def _login_needs_captcha(db, ip: str) -> bool:
    mode = current_app.config["CAPTCHA_ON_LOGIN"]
    if mode == "always":
        return True
    if mode == "never":
        return False
    return rate_count(db, f"loginfail:{ip}", 900) >= current_app.config["CAPTCHA_AFTER_FAILS"]


@bp.route("/login", methods=("GET", "POST"))
def login():
    nxt = safe_next(request.values.get("next"))
    if g.user:
        return redirect(nxt or url_for("shop.index"))
    db = get_db()
    ip = client_ip()
    cfg = current_app.config
    identifier, errors = "", {}

    if request.method == "POST":
        identifier = (request.form.get("identifier") or "").strip()[:254]
        password = (request.form.get("password") or "")[:256]
        remember = bool(request.form.get("remember"))

        if rate_limited(db, f"loginfail:{ip}", cfg["LOGIN_IP_FAIL_LIMIT"], 900):
            log_event("login_blocked", details="лимит попыток с адреса", username=identifier[:64])
            too_many("С вашего адреса слишком много неудачных входов. Попробуйте через 15 минут.")

        if _login_needs_captcha(db, ip) and not _check_captcha(db):
            errors["captcha"] = CAPTCHA_ERROR
        else:
            user = find_user(db, identifier)
            now = time.time()
            if user and user["locked_until"] > now:
                minutes = max(1, math.ceil((user["locked_until"] - now) / 60))
                errors["form"] = (f"Аккаунт временно заблокирован из-за серии неудачных входов. "
                                  f"Повторите через {minutes} мин. или восстановите пароль.")
                log_event("login_blocked", user=user, details="аккаунт заблокирован")
            elif verify_password(user["password_hash"] if user else None, password) and user:
                if not user["is_active"]:
                    errors["form"] = "Аккаунт заблокирован администратором."
                    log_event("login_blocked", user=user, details="аккаунт отключён")
                else:
                    db.execute(
                        "UPDATE users SET failed_logins = 0, locked_until = 0, last_login_at = ? WHERE id = ?",
                        (now, user["id"]),
                    )
                    login_user(user, remember)
                    log_event("login_success", user=user)
                    flash(f"С возвращением, {user['username']}.", "ok")
                    return redirect(nxt or url_for("shop.index"))
            else:
                rate_hit(db, f"loginfail:{ip}")
                errors["form"] = "Неверное имя пользователя или пароль."
                if user:
                    db.execute("UPDATE users SET failed_logins = failed_logins + 1 WHERE id = ?", (user["id"],))
                    fails = db.execute("SELECT failed_logins FROM users WHERE id = ?", (user["id"],)).fetchone()[0]
                    log_event("login_failed", user=user, details=f"подряд ошибок: {fails}")
                    if fails >= cfg["LOGIN_LOCK_AFTER"]:
                        db.execute(
                            "UPDATE users SET failed_logins = 0, locked_until = ? WHERE id = ?",
                            (now + cfg["LOGIN_LOCK_SECONDS"], user["id"]),
                        )
                        log_event("account_locked", user=user)
                        errors["form"] = ("Слишком много неверных паролей: аккаунт заблокирован на "
                                          f"{cfg['LOGIN_LOCK_SECONDS'] // 60} мин.")
                else:
                    log_event("login_failed", details="неизвестный пользователь", username=identifier[:64])

    needs_captcha = _login_needs_captcha(db, ip)
    return render_template("auth/login.html", identifier=identifier, errors=errors, next=nxt,
                           captcha=_fresh_captcha(db) if needs_captcha else None)


@bp.post("/logout")
def logout():
    from flask import session
    if g.user:
        log_event("logout", user=g.user)
    session.clear()
    flash("Вы вышли из аккаунта.", "ok")
    return redirect(url_for("shop.index"))


# ───────────────────────── восстановление пароля ─────────────────────────


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@bp.route("/forgot", methods=("GET", "POST"))
def forgot():
    if g.user:
        return redirect(url_for("account.profile"))
    db = get_db()
    errors, sent, email = {}, False, ""

    if request.method == "POST":
        ip = client_ip()
        email = (request.form.get("email") or "").strip().lower()
        if rate_limited(db, f"forgot:{ip}", 6, 3600):
            too_many("Слишком много запросов на восстановление. Попробуйте через час.")
        rate_hit(db, f"forgot:{ip}")

        if not _check_captcha(db):
            errors["captcha"] = CAPTCHA_ERROR
        elif msg := validate_email(email):
            errors["email"] = msg
        else:
            sent = True  # отвечаем одинаково, есть такой адрес или нет
            email_key = hashlib.sha256(email.encode()).hexdigest()[:16]
            if not rate_limited(db, f"forgot-mail:{email_key}", 3, 3600):
                rate_hit(db, f"forgot-mail:{email_key}")
                user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
                if user and user["is_active"]:
                    _send_reset(db, user)

    return render_template("auth/forgot.html", errors=errors, sent=sent, email=email,
                           captcha=_fresh_captcha(db))


def _send_reset(db, user):
    now = time.time()
    token = secrets.token_urlsafe(32)
    db.execute("UPDATE password_resets SET used_at = ? WHERE user_id = ? AND used_at IS NULL", (now, user["id"]))
    db.execute(
        "INSERT INTO password_resets(user_id, token_hash, expires_at, created_at) VALUES (?,?,?,?)",
        (user["id"], _hash_token(token), now + current_app.config["RESET_TOKEN_TTL"], now),
    )
    link = url_for("auth.reset", token=token, _external=True)
    minutes = current_app.config["RESET_TOKEN_TTL"] // 60
    mailer.send_email(
        user["email"], "ТёмныйФефу: сброс пароля",
        f"Здравствуйте, {user['username']}!\n\n"
        f"Кто-то запросил сброс пароля для вашего аккаунта. Если это вы, откройте ссылку "
        f"(она действует {minutes} минут и работает один раз):\n\n{link}\n\n"
        "Если вы ничего не запрашивали, просто проигнорируйте это письмо — пароль останется прежним.",
    )
    log_event("password_reset_requested", user=user)


def _valid_reset(db, token: str):
    return db.execute(
        "SELECT pr.id, pr.user_id FROM password_resets pr JOIN users u ON u.id = pr.user_id"
        " WHERE pr.token_hash = ? AND pr.used_at IS NULL AND pr.expires_at > ? AND u.is_active = 1",
        (_hash_token(token), time.time()),
    ).fetchone()


@bp.route("/reset/<token>", methods=("GET", "POST"))
def reset(token):
    db = get_db()
    row = _valid_reset(db, token[:100])
    if row is None:
        return render_template("auth/reset.html", invalid=True, errors={}), 400
    user = user_by_id(db, row["user_id"])
    errors = {}

    if request.method == "POST":
        password = request.form.get("password") or ""
        if msg := validate_password(password, user["username"], user["email"]):
            errors["password"] = msg
        elif password != (request.form.get("password2") or ""):
            errors["password2"] = "Пароли не совпадают."
        else:
            now = time.time()
            db.execute(
                "UPDATE users SET password_hash = ?, session_version = session_version + 1,"
                " failed_logins = 0, locked_until = 0 WHERE id = ?",
                (hash_password(password), user["id"]),
            )
            db.execute("UPDATE password_resets SET used_at = ? WHERE user_id = ? AND used_at IS NULL",
                       (now, user["id"]))
            log_event("password_reset_done", user=user)
            mailer.send_email(
                user["email"], "ТёмныйФефу: пароль изменён",
                f"Здравствуйте, {user['username']}!\n\nПароль вашего аккаунта был изменён по ссылке "
                "восстановления. Все прежние входы завершены. Если это были не вы — немедленно "
                "восстановите доступ ещё раз и напишите администратору.",
            )
            flash("Пароль изменён. Теперь можно войти.", "ok")
            return redirect(url_for("auth.login"))

    return render_template("auth/reset.html", invalid=False, errors=errors, username=user["username"])


# ───────────────────────── письма в режиме разработки ─────────────────────────


@bp.get("/dev/outbox")
def dev_outbox():
    if not current_app.config["DEV_OUTBOX"]:
        abort(404)
    rows = get_db().execute("SELECT * FROM outbox ORDER BY id DESC LIMIT 30").fetchall()
    return render_template("dev_outbox.html", rows=rows)
