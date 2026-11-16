"""Кошелёк: баланс, ежедневный бонус с серией, переводы между студентами, история."""
import time

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from . import wallet
from .audit import log_event
from .db import get_db, transaction
from .security import login_required, normalize_username, rate_hit, rate_limited, too_many, username_key

bp = Blueprint("wallet", __name__)
DAILY_BASE, DAILY_STEP, MAX_STREAK, COOLDOWN, KEEP_ALIVE = 20, 10, 7, 20 * 3600, 48 * 3600
EARN_KINDS = ("mine", "passive", "bus", "casino_win", "daily", "sale")


def _daily(db, uid, now):
    gs = db.execute("SELECT daily_streak, last_daily FROM game_state WHERE user_id = ?", (uid,)).fetchone()
    last, streak = gs["last_daily"], gs["daily_streak"] if now - gs["last_daily"] < KEEP_ALIVE else 0
    nxt = min(streak + 1, MAX_STREAK)
    return {"streak": streak, "ready": now - last >= COOLDOWN, "wait": max(0, int(last + COOLDOWN - now)),
            "reward": DAILY_BASE + DAILY_STEP * (nxt - 1), "next": nxt, "last": last}


@bp.get("/wallet")
@login_required
def page():
    db, uid, now = get_db(), g.user["id"], time.time()
    d = _daily(db, uid, now)
    marks = ",".join("?" * len(EARN_KINDS))
    earned = db.execute(f"SELECT COALESCE(SUM(amount), 0) FROM wallet_tx WHERE user_id = ? AND kind IN ({marks})", (uid, *EARN_KINDS)).fetchone()[0]
    spent = db.execute("SELECT COALESCE(-SUM(amount), 0) FROM wallet_tx WHERE user_id = ? AND kind = 'purchase'", (uid,)).fetchone()[0]
    history = db.execute("SELECT * FROM wallet_tx WHERE user_id = ? ORDER BY id DESC LIMIT 50", (uid,)).fetchall()
    return render_template("wallet.html", d=d, wait=f"{d['wait'] // 3600} ч {d['wait'] % 3600 // 60} мин",
                           earned=earned, spent=spent, history=history, kind_labels=wallet.KIND_LABELS)


@bp.post("/wallet/daily")
@login_required
def daily():
    db, uid, now = get_db(), g.user["id"], time.time()
    with transaction(db):
        d = _daily(db, uid, now)
        if not d["ready"]:
            flash("Бонус уже забран. Возвращайтесь позже.", "error")
        elif db.execute("UPDATE game_state SET daily_streak = ?, last_daily = ? WHERE user_id = ? AND last_daily = ?",
                        (d["next"], now, uid, d["last"])).rowcount == 1:
            wallet.apply(db, uid, d["reward"], "daily", f"Серия: {d['next']}-й день")
            flash(f"+{d['reward']} зачёток. Серия: {d['next']}-й день.", "ok")
    return redirect(url_for("wallet.page"))


@bp.post("/wallet/send")
@login_required
def send():
    db, uid = get_db(), g.user["id"]
    if rate_limited(db, f"send:{uid}", 10, 3600):
        too_many("Слишком много переводов за час.")
    rate_hit(db, f"send:{uid}")
    name = normalize_username(request.form.get("to"))
    amount = request.form.get("amount", type=int)
    to = db.execute("SELECT * FROM users WHERE username_key = ? AND is_active = 1", (username_key(name),)).fetchone()
    if to is None or to["id"] == uid:
        flash("Получатель не найден (и себе переводить нельзя).", "error")
    elif amount is None or not 1 <= amount <= 1000:
        flash("Сумма перевода: от 1 до 1000 зачёток.", "error")
    else:
        try:
            with transaction(db):
                wallet.apply(db, uid, -amount, "transfer_out", f"Для {to['username']}")
                wallet.apply(db, to["id"], amount, "transfer_in", f"От {g.user['username']}")
        except wallet.InsufficientFunds:
            flash("Не хватает зачёток для перевода.", "error")
        else:
            log_event("transfer", user=g.user, details=f"{amount} → {to['username']}")
            flash(f"Отправлено {amount} зачёток пользователю {to['username']}.", "ok")
    return redirect(url_for("wallet.page"))
