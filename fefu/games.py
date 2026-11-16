"""Мини-игры для пополнения баланса. Вся арифметика и случайность — на сервере."""
import random
import time

from flask import Blueprint, g, jsonify, render_template, request

from . import wallet
from .db import get_db, transaction
from .security import login_required

bp = Blueprint("games", __name__)

UPGRADES = [
    {"key": "energy", "name": "Энергетик", "desc": "+1 зачётка за клик", "base": 50, "click": 1, "sec": 0},
    {"key": "cheat", "name": "Шпаргалка", "desc": "+1 зачётка в секунду", "base": 100, "click": 0, "sec": 1},
    {"key": "starosta", "name": "Староста", "desc": "+5 зачёток в секунду", "base": 400, "click": 0, "sec": 5},
]
UPGRADE_BY_KEY = {u["key"]: u for u in UPGRADES}
MAX_OWNED = 60
OFFLINE_CAP = 3600          # пассивный доход копится не дольше часа

MINE_MIN_INTERVAL = 0.3     # не чаще одной пачки кликов за 0,3 с
MINE_RATE = 14              # правдоподобный максимум кликов в секунду
MINE_BURST = 2
MINE_MAX_BATCH = 40

BUS_GOAL, BUS_TIME, BUS_GRACE, BUS_MIN_TIME = 15, 5.0, 1.5, 0.8
BUS_REWARD, BUS_COOLDOWN = 40, 8

BETS = (10, 20, 50)
SYMBOLS = ["🎓", "📈", "🚌", "🍛", "💀"]
SPIN_COOLDOWN = 1.2
_rng = random.SystemRandom()

BUS_FAILS = [
    "Автобус уехал. Ты остался(-ась) на остановке с ещё 200 людьми.",
    "Двери закрылись прямо перед носом. Классика.",
    "Автобус был забит, водитель только вздохнул и уехал.",
]


def _err(message: str, status: int = 400, **extra):
    return jsonify(ok=False, error=message, **extra), status


def _cost(upgrade: dict, owned: int) -> int:
    return int(upgrade["base"] * 1.5 ** owned + 0.5)


def _levels(db, uid: int) -> dict:
    return {r["upgrade_key"]: r["owned"] for r in
            db.execute("SELECT upgrade_key, owned FROM user_upgrades WHERE user_id = ?", (uid,))}


def _rates(levels: dict):
    per_click = 1 + sum(levels.get(u["key"], 0) * u["click"] for u in UPGRADES)
    per_sec = sum(levels.get(u["key"], 0) * u["sec"] for u in UPGRADES)
    return per_click, per_sec


def _state_row(db, uid: int):
    db.execute("INSERT OR IGNORE INTO game_state(user_id, last_collect) VALUES (?, ?)", (uid, time.time()))
    return db.execute("SELECT * FROM game_state WHERE user_id = ?", (uid,)).fetchone()


def _collect(db, uid: int, now: float):
    """Начисляет пассивный доход за прошедшее время (внутри транзакции)."""
    st = _state_row(db, uid)
    _, per_sec = _rates(_levels(db, uid))
    elapsed = max(0.0, now - st["last_collect"])
    if per_sec == 0 or elapsed > OFFLINE_CAP:
        gain_secs, new_mark = (0 if per_sec == 0 else int(OFFLINE_CAP)), now
    else:
        gain_secs = int(elapsed)
        new_mark = st["last_collect"] + gain_secs
    if gain_secs and per_sec:
        wallet.apply(db, uid, gain_secs * per_sec, "passive", "Пассивный доход", merge=True)
    db.execute("UPDATE game_state SET last_collect = ? WHERE user_id = ?", (new_mark, uid))


def _snapshot(db, uid: int, now: float) -> dict:
    levels = _levels(db, uid)
    per_click, per_sec = _rates(levels)
    st = _state_row(db, uid)
    balance = db.execute("SELECT balance FROM users WHERE id = ?", (uid,)).fetchone()[0]
    return {
        "ok": True,
        "balance": balance,
        "per_click": per_click,
        "per_sec": per_sec,
        "upgrades": [
            {**{k: u[k] for k in ("key", "name", "desc")},
             "owned": levels.get(u["key"], 0),
             "cost": _cost(u, levels.get(u["key"], 0)),
             "maxed": levels.get(u["key"], 0) >= MAX_OWNED}
            for u in UPGRADES
        ],
        "bus_wait": max(0, round(st["bus_cooldown_until"] - now, 1)),
    }


@bp.get("/games")
@login_required
def page():
    return render_template("games.html", bets=BETS, bus_goal=BUS_GOAL, bus_time=int(BUS_TIME),
                           bus_reward=BUS_REWARD, symbols=SYMBOLS)


@bp.get("/api/games/state")
@login_required
def state():
    db, now = get_db(), time.time()
    with transaction(db):
        _collect(db, g.user["id"], now)
    return jsonify(_snapshot(db, g.user["id"], now))


@bp.post("/api/games/mine")
@login_required
def mine():
    db, now, uid = get_db(), time.time(), g.user["id"]
    clicks = (request.get_json(silent=True) or {}).get("clicks", 0)
    if not isinstance(clicks, int) or isinstance(clicks, bool) or clicks < 0:
        return _err("Некорректные данные.")
    with transaction(db):
        _collect(db, uid, now)
        st = _state_row(db, uid)
        elapsed = now - st["last_mine"]
        if clicks and elapsed < MINE_MIN_INTERVAL:
            return _err("Слишком быстро. Даже зачётки майнятся не мгновенно.", 429)
        allowed = min(MINE_MAX_BATCH, int(min(elapsed, 3.0) * MINE_RATE) + MINE_BURST)
        accepted = min(clicks, allowed)
        per_click, _ = _rates(_levels(db, uid))
        if accepted:
            wallet.apply(db, uid, accepted * per_click, "mine", "Майнинг зачёток", merge=True)
            db.execute("UPDATE game_state SET last_mine = ? WHERE user_id = ?", (now, uid))
    snap = _snapshot(db, uid, now)
    snap["accepted"] = accepted
    return jsonify(snap)


@bp.post("/api/games/upgrade")
@login_required
def upgrade():
    db, now, uid = get_db(), time.time(), g.user["id"]
    key = (request.get_json(silent=True) or {}).get("key")
    spec = UPGRADE_BY_KEY.get(key)
    if spec is None:
        return _err("Нет такого улучшения.", 404)
    try:
        with transaction(db):
            _collect(db, uid, now)
            owned = _levels(db, uid).get(key, 0)
            if owned >= MAX_OWNED:
                return _err("Улучшение уже прокачано до максимума.", 409)
            wallet.apply(db, uid, -_cost(spec, owned), "upgrade", f"Улучшение «{spec['name']}»")
            db.execute(
                "INSERT INTO user_upgrades(user_id, upgrade_key, owned) VALUES (?,?,1)"
                " ON CONFLICT(user_id, upgrade_key) DO UPDATE SET owned = owned + 1",
                (uid, key),
            )
    except wallet.InsufficientFunds:
        return _err("Не хватает зачёток на улучшение. Покликай ещё.", 409)
    return jsonify(_snapshot(db, uid, now))


@bp.post("/api/games/bus/start")
@login_required
def bus_start():
    db, now, uid = get_db(), time.time(), g.user["id"]
    with transaction(db):
        st = _state_row(db, uid)
        if now < st["bus_cooldown_until"]:
            wait = round(st["bus_cooldown_until"] - now, 1)
            return _err(f"Следующий автобус через {wait} с.", 429, wait=wait)
        db.execute("UPDATE game_state SET bus_started = ? WHERE user_id = ?", (now, uid))
    return jsonify(ok=True, goal=BUS_GOAL, seconds=BUS_TIME)


@bp.post("/api/games/bus/finish")
@login_required
def bus_finish():
    db, now, uid = get_db(), time.time(), g.user["id"]
    pushes = (request.get_json(silent=True) or {}).get("pushes", 0)
    if not isinstance(pushes, int) or isinstance(pushes, bool):
        return _err("Некорректные данные.")
    with transaction(db):
        st = _state_row(db, uid)
        started = st["bus_started"]
        if not started:
            return _err("Вы не вставали в очередь на автобус.", 409)
        elapsed = now - started
        db.execute("UPDATE game_state SET bus_started = 0, bus_cooldown_until = ? WHERE user_id = ?",
                   (now + BUS_COOLDOWN, uid))
        reached = pushes >= BUS_GOAL
        if reached and elapsed < BUS_MIN_TIME:
            won, message = False, "Слишком быстро: так протискиваться не умеет даже курьер."
        elif reached and elapsed <= BUS_TIME + BUS_GRACE:
            won = True
            wallet.apply(db, uid, BUS_REWARD, "bus", "Место в автобусе")
            message = f"Влез(-ла)! Стоишь на одной ноге, зато едешь. +{BUS_REWARD} зачёток."
        else:
            won, message = False, _rng.choice(BUS_FAILS)
    snap = _snapshot(db, uid, now)
    snap.update(won=won, message=message)
    return jsonify(snap)


def _spin_result(bet: int):
    result = [_rng.choice(SYMBOLS) for _ in range(3)]
    a, b, c = result
    if a == b == c:
        if a == "💀":
            return result, 0, "skulls", "Три черепа. Ну лян, с кем не бывает..."
        return result, bet * 10, "jackpot", f"ДЖЕКПОТ! Три {a}. Выигрыш: {bet * 10} зачёток."
    if a == b or b == c or a == c:
        return result, bet, "pair", "Два одинаковых. Ставка возвращается, но осадочек остался."
    return result, 0, "miss", "Мимо. Казино благодарит за вклад в стипендиальный фонд."


@bp.post("/api/games/spin")
@login_required
def spin():
    db, now, uid = get_db(), time.time(), g.user["id"]
    bet = (request.get_json(silent=True) or {}).get("bet")
    if bet not in BETS or isinstance(bet, bool):
        return _err("Такой ставки нет.")
    try:
        with transaction(db):
            st = _state_row(db, uid)
            if now - st["last_spin"] < SPIN_COOLDOWN:
                return _err("Барабаны ещё крутятся.", 429)
            wallet.apply(db, uid, -bet, "casino_bet", f"Ставка {bet}")
            reels, payout, outcome, message = _spin_result(bet)
            if payout:
                wallet.apply(db, uid, payout, "casino_win", f"Выплата {payout}")
            db.execute("UPDATE game_state SET last_spin = ? WHERE user_id = ?", (now, uid))
    except wallet.InsufficientFunds:
        return _err("Недостаточно зачёток. Казино в долг не играет.", 409)
    snap = _snapshot(db, uid, now)
    snap.update(reels=reels, outcome=outcome, message=message, payout=payout)
    return jsonify(snap)
