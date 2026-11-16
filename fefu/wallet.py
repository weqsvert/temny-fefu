"""Кошелёк. Любое изменение баланса идёт через apply() и попадает в журнал."""
import time


class InsufficientFunds(Exception):
    pass


MERGE_WINDOW = 60  # секунд: клики майнинга склеиваем в одну строку журнала


def apply(db, user_id: int, delta: int, kind: str, note: str = "", merge: bool = False) -> int:
    """Меняет баланс на delta. Баланс не может уйти в минус: проверка на уровне UPDATE.

    Вызывать внутри transaction(), если операция состоит из нескольких шагов.
    Возвращает новый баланс.
    """
    delta = int(delta)
    cur = db.execute(
        "UPDATE users SET balance = balance + ? WHERE id = ? AND balance + ? >= 0",
        (delta, user_id, delta),
    )
    if cur.rowcount != 1:
        raise InsufficientFunds()
    balance = db.execute("SELECT balance FROM users WHERE id = ?", (user_id,)).fetchone()[0]
    if delta == 0:
        return balance
    now = time.time()
    if merge:
        last = db.execute(
            "SELECT id, kind, created_at FROM wallet_tx WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if last and last["kind"] == kind and now - last["created_at"] < MERGE_WINDOW:
            db.execute(
                "UPDATE wallet_tx SET amount = amount + ?, balance_after = ? WHERE id = ?",
                (delta, balance, last["id"]),
            )
            return balance
    db.execute(
        "INSERT INTO wallet_tx(user_id, amount, balance_after, kind, note, created_at) VALUES (?,?,?,?,?,?)",
        (user_id, delta, balance, kind, note, now),
    )
    return balance


KIND_LABELS = {
    "signup_bonus": "Приветственный бонус",
    "purchase": "Покупка",
    "refund": "Возврат за заказ",
    "mine": "Майнинг",
    "passive": "Пассивный доход",
    "upgrade": "Улучшение",
    "bus": "Автобус",
    "casino_bet": "Ставка в казино",
    "casino_win": "Выигрыш в казино",
    "daily": "Ежедневный бонус",
    "transfer_out": "Перевод",
    "transfer_in": "Входящий перевод",
    "sale": "Продажа товара",
    "admin_adjust": "Корректировка администратором",
}
