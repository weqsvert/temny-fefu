"""Личный кабинет."""
import sqlite3

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from . import mailer, wallet
from .audit import EVENT_LABELS, SECURITY_EVENTS, log_event
from .db import get_db
from .security import (hash_password, login_required, rate_hit, rate_limited, too_many,
                       validate_email, validate_password, verify_password)

bp = Blueprint("account", __name__, url_prefix="/account")


def _guard_password(db, section: str) -> bool:
    """Проверяет текущий пароль из формы. Считает неудачи и ограничивает перебор."""
    key = f"pwcheck:{g.user['id']}"
    if rate_limited(db, key, 5, 900):
        too_many("Слишком много неверных паролей подряд. Подождите 15 минут.")
    if verify_password(g.user["password_hash"], request.form.get("current_password") or ""):
        return True
    rate_hit(db, key)
    flash("Текущий пароль указан неверно.", "error")
    return False


def _back(section: str):
    return redirect(url_for("account.profile") + f"#{section}")


@bp.get("")
@login_required
def profile():
    db = get_db()
    uid = g.user["id"]
    marks = ",".join("?" * len(SECURITY_EVENTS))
    events = db.execute(
        f"SELECT * FROM audit_log WHERE user_id = ? AND event IN ({marks}) ORDER BY id DESC LIMIT 15",
        (uid, *SECURITY_EVENTS),
    ).fetchall()
    history = db.execute(
        "SELECT * FROM wallet_tx WHERE user_id = ? ORDER BY id DESC LIMIT 20", (uid,)
    ).fetchall()
    stats = db.execute(
        "SELECT COUNT(*) AS orders, COALESCE(SUM(total), 0) AS spent FROM orders"
        " WHERE user_id = ? AND status != 'cancelled'", (uid,)
    ).fetchone()
    return render_template("account.html", events=events, history=history, stats=stats,
                           event_labels=EVENT_LABELS, kind_labels=wallet.KIND_LABELS)


@bp.post("/password")
@login_required
def change_password():
    db = get_db()
    if not _guard_password(db, "password"):
        return _back("password")
    new, again = request.form.get("new_password") or "", request.form.get("new_password2") or ""
    if msg := validate_password(new, g.user["username"], g.user["email"]):
        flash(msg, "error")
    elif new == (request.form.get("current_password") or ""):
        flash("Новый пароль должен отличаться от текущего.", "error")
    elif new != again:
        flash("Новые пароли не совпадают.", "error")
    else:
        db.execute(
            "UPDATE users SET password_hash = ?, session_version = session_version + 1 WHERE id = ?",
            (hash_password(new), g.user["id"]),
        )
        new_version = db.execute("SELECT session_version FROM users WHERE id = ?", (g.user["id"],)).fetchone()[0]
        session["sv"] = new_version  # текущая сессия остаётся, остальные закрываются
        log_event("password_changed", user=g.user)
        mailer.send_email(g.user["email"], "ТёмныйФефу: пароль изменён",
                          f"Здравствуйте, {g.user['username']}!\n\nПароль вашего аккаунта только что изменён. "
                          "Все остальные устройства разлогинены. Если это были не вы — срочно восстановите доступ.")
        flash("Пароль изменён. На остальных устройствах вы вышли.", "ok")
    return _back("password")


@bp.post("/email")
@login_required
def change_email():
    db = get_db()
    if not _guard_password(db, "email"):
        return _back("email")
    email = (request.form.get("email") or "").strip().lower()
    if msg := validate_email(email):
        flash(msg, "error")
    elif email == g.user["email"]:
        flash("Это уже ваш адрес.", "error")
    else:
        old = g.user["email"]
        try:
            db.execute("UPDATE users SET email = ? WHERE id = ?", (email, g.user["id"]))
        except sqlite3.IntegrityError:
            flash("Эта почта уже занята другим аккаунтом.", "error")
        else:
            log_event("email_changed", user=g.user, details=f"{old} → {email}")
            mailer.send_email(old, "ТёмныйФефу: адрес почты изменён",
                              f"Адрес почты аккаунта {g.user['username']} изменён на {email}. "
                              "Если это были не вы — срочно смените пароль.")
            flash("Адрес почты обновлён.", "ok")
    return _back("email")


@bp.post("/logout-everywhere")
@login_required
def logout_everywhere():
    db = get_db()
    db.execute("UPDATE users SET session_version = session_version + 1 WHERE id = ?", (g.user["id"],))
    new_version = db.execute("SELECT session_version FROM users WHERE id = ?", (g.user["id"],)).fetchone()[0]
    session["sv"] = new_version
    log_event("logout_everywhere", user=g.user)
    flash("Все остальные устройства разлогинены.", "ok")
    return _back("sessions")


@bp.post("/delete")
@login_required
def delete_account():
    db = get_db()
    if not _guard_password(db, "danger"):
        return _back("danger")
    if (request.form.get("confirm") or "").strip().casefold() != "удалить":
        flash("Напишите слово «удалить», чтобы подтвердить.", "error")
        return _back("danger")
    if g.user["role"] == "admin" and db.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
    ).fetchone()[0] <= 1:
        flash("Вы единственный администратор. Сначала назначьте другого.", "error")
        return _back("danger")
    log_event("account_deleted", user=g.user)
    db.execute("DELETE FROM users WHERE id = ?", (g.user["id"],))
    session.clear()
    flash("Аккаунт удалён. Зачётки сгорели вместе с ним.", "ok")
    return redirect(url_for("shop.index"))
