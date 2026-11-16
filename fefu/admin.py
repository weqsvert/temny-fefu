"""Админ-панель: пользователи, баланс, журнал событий."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from . import wallet
from .accounts import user_by_id
from .audit import log_event
from .db import get_db, transaction
from .security import admin_required

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.get("")
@admin_required
def index():
    db = get_db()
    stats = db.execute("SELECT (SELECT COUNT(*) FROM users) AS users, (SELECT COUNT(*) FROM orders) AS orders, "
                       "(SELECT COALESCE(SUM(balance), 0) FROM users) AS coins").fetchone()
    return render_template("admin.html", stats=stats,
                           users=db.execute("SELECT * FROM users ORDER BY id").fetchall(),
                           events=db.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 40").fetchall())


def _target(uid):
    user = user_by_id(get_db(), uid)
    if user is None:
        abort(404)
    return user


@bp.post("/users/<int:uid>/toggle")
@admin_required
def toggle(uid):
    user = _target(uid)
    if user["id"] == g.user["id"]:
        flash("Себя блокировать нельзя.", "error")
    else:
        get_db().execute("UPDATE users SET is_active = 1 - is_active, session_version = session_version + 1 "
                         "WHERE id = ?", (uid,))
        log_event("admin_toggle", user=g.user, details=f"пользователь {user['username']}")
        flash("Статус аккаунта изменён.", "ok")
    return redirect(url_for("admin.index"))


@bp.post("/users/<int:uid>/balance")
@admin_required
def balance(uid):
    user, db = _target(uid), get_db()
    delta = request.form.get("amount", type=int)
    if delta is None or not -100000 <= delta <= 100000 or delta == 0:
        flash("Сумма: целое число от −100 000 до 100 000, не ноль.", "error")
    else:
        try:
            with transaction(db):
                wallet.apply(db, uid, delta, "admin_adjust", f"Администратор {g.user['username']}")
            log_event("admin_adjust", user=g.user, details=f"{user['username']}: {delta:+d}")
            flash("Баланс изменён.", "ok")
        except wallet.InsufficientFunds:
            flash("Баланс не может уйти в минус.", "error")
    return redirect(url_for("admin.index"))
