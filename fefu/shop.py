"""Каталог, корзина, заказы, отзывы."""
import sqlite3
import time
from urllib.parse import urlparse

from flask import Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request, url_for

from . import wallet
from .db import get_db, transaction
from .security import login_required, safe_next, wants_json

bp = Blueprint("shop", __name__)
PAGE_SIZE = 12
SORTS = {
    "new": ("По порядку", "p.id"),
    "cheap": ("Сначала дешёвые", "p.price, p.id"),
    "dear": ("Сначала дорогие", "p.price DESC, p.id"),
    "rating": ("По оценке", "avg DESC, n DESC, p.id"),
}
TRACK = ["Заказ принят", "Курьер найден", "Курьер потерян", "Курьер найден на нижних этажах корпуса E",
         "Выход из корпуса E не найден", "Доставлено"]
RATED = ("SELECT p.*, COALESCE(AVG(r.rating), 0) AS avg, COUNT(r.id) AS n FROM products p "
         "LEFT JOIN reviews r ON r.product_id = p.id")


class OutOfStock(Exception):
    pass


def _back() -> str:
    ref = urlparse(request.referrer or "")
    return safe_next(ref.path + (f"?{ref.query}" if ref.query else "")) or url_for("shop.index")


def _guest():
    if wants_json():
        return jsonify(ok=False, error="Войдите, чтобы продолжить.", login=url_for("auth.login")), 401
    flash("Войдите, чтобы продолжить.", "error")
    return redirect(url_for("auth.login", next=_back()))


@bp.get("/")
def index():
    db = get_db()
    q = (request.args.get("q") or "").strip()[:80]
    cat = request.args.get("cat") or ""
    sort = request.args.get("sort") if request.args.get("sort") in SORTS else "new"
    where, args = ["p.is_active = 1 AND status = 'approved'"], []
    if q:
        like = "%" + q.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(casefold(p.name) LIKE ? ESCAPE '\\' OR casefold(p.description) LIKE ? ESCAPE '\\')")
        args += [like, like]
    if cat:
        where.append("p.category = ?")
        args.append(cat)
    cond = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM products p WHERE {cond}", args).fetchone()[0]
    pages = max(1, -(-total // PAGE_SIZE))
    page = min(max(1, request.args.get("page", 1, type=int)), pages)
    items = db.execute(f"{RATED} WHERE {cond} GROUP BY p.id ORDER BY {SORTS[sort][1]} LIMIT ? OFFSET ?",
                       [*args, PAGE_SIZE, (page - 1) * PAGE_SIZE]).fetchall()
    cats = db.execute("SELECT category, COUNT(*) AS n FROM products WHERE is_active = 1 AND status = 'approved' "
                      "GROUP BY category ORDER BY category").fetchall()
    return render_template("shop/index.html", items=items, cats=cats, pulse=_pulse(db), q=q, cat=cat, sort=sort,
                           sorts=SORTS, page=page, pages=pages, total=total)


@bp.get("/p/<int:pid>")
def product(pid):
    db = get_db()
    p = db.execute(f"{RATED} WHERE p.id = ? AND p.is_active = 1 AND status = 'approved' GROUP BY p.id", (pid,)).fetchone()
    if p is None:
        abort(404)
    uid = g.user["id"] if g.user else 0
    reviews = db.execute(
        "SELECT r.*, (SELECT COUNT(*) FROM review_votes v WHERE v.review_id = r.id) AS votes, "
        "EXISTS(SELECT 1 FROM review_votes v WHERE v.review_id = r.id AND v.user_id = ?) AS voted, "
        "EXISTS(SELECT 1 FROM order_items oi JOIN orders o ON o.id = oi.order_id WHERE oi.product_id = r.product_id "
        "AND o.user_id = r.user_id AND o.status != 'cancelled') AS bought "
        "FROM reviews r WHERE r.product_id = ? ORDER BY votes DESC, r.created_at DESC", (uid, pid)).fetchall()
    mine = any(r["user_id"] == uid for r in reviews)
    seller = db.execute("SELECT username FROM users WHERE id = ?", (p["seller_id"],)).fetchone()
    return render_template("shop/product.html", p=p, reviews=reviews, reviewed=mine, seller=seller and seller["username"])


@bp.post("/p/<int:pid>/review")
def review(pid):
    if not g.user:
        return _guest()
    db = get_db()
    rating = request.form.get("rating", type=int)
    body = (request.form.get("body") or "").strip()
    if not db.execute("SELECT 1 FROM products WHERE id = ? AND is_active = 1 AND status = 'approved'", (pid,)).fetchone():
        abort(404)
    if rating not in range(1, 6) or not 5 <= len(body) <= 500:
        flash("Поставьте оценку и напишите отзыв от 5 до 500 символов.", "error")
    else:
        try:
            db.execute("INSERT INTO reviews(product_id, user_id, author, rating, body, created_at) "
                       "VALUES (?,?,?,?,?,?)", (pid, g.user["id"], g.user["username"], rating, body, time.time()))
            flash("Отзыв опубликован.", "ok")
        except sqlite3.IntegrityError:
            flash("Вы уже оставляли отзыв на этот товар.", "error")
    return redirect(url_for("shop.product", pid=pid) + "#reviews")


def _cart_rows(db, uid):
    return db.execute("SELECT p.*, c.qty FROM cart_items c JOIN products p ON p.id = c.product_id "
                      "WHERE c.user_id = ? AND p.is_active = 1 AND status = 'approved' ORDER BY p.name", (uid,)).fetchall()


@bp.get("/cart")
@login_required
def cart():
    rows = _cart_rows(get_db(), g.user["id"])
    return render_template("shop/cart.html", rows=rows, total=sum(r["price"] * r["qty"] for r in rows))


@bp.post("/cart/add")
def cart_add():
    if not g.user:
        return _guest()
    db = get_db()
    qty = min(20, max(1, request.form.get("qty", 1, type=int)))
    p = db.execute("SELECT * FROM products WHERE id = ? AND is_active = 1 AND status = 'approved'",
                   (request.form.get("product_id", type=int),)).fetchone()
    if p is None:
        abort(404)
    have = db.execute("SELECT qty FROM cart_items WHERE user_id = ? AND product_id = ?",
                      (g.user["id"], p["id"])).fetchone()
    limit = 20 if p["stock"] is None else min(20, p["stock"])
    new = min(limit, (have["qty"] if have else 0) + qty)
    prev = have["qty"] if have else 0
    msg, ok = "Этого товара больше нет в наличии.", False
    if new >= 1:
        db.execute("INSERT INTO cart_items(user_id, product_id, qty) VALUES (?,?,?) "
                   "ON CONFLICT(user_id, product_id) DO UPDATE SET qty = excluded.qty", (g.user["id"], p["id"], new))
        msg, ok = f"«{p['name']}» в корзине" + (" (достигнут лимит)." if new < prev + qty else "."), True
    if wants_json():
        count = db.execute("SELECT COALESCE(SUM(qty), 0) FROM cart_items WHERE user_id = ?", (g.user["id"],)).fetchone()[0]
        return jsonify(ok=ok, message=msg, error=msg, count=count)
    flash(msg, "ok" if ok else "error")
    return redirect(_back())


@bp.post("/cart/update")
@login_required
def cart_update():
    db, pid = get_db(), request.form.get("product_id", type=int)
    qty = request.form.get("qty", type=int)
    if qty is None or qty < 1:
        db.execute("DELETE FROM cart_items WHERE user_id = ? AND product_id = ?", (g.user["id"], pid))
    else:
        p = db.execute("SELECT stock FROM products WHERE id = ?", (pid,)).fetchone()
        limit = 20 if not p or p["stock"] is None else min(20, p["stock"])
        db.execute("UPDATE cart_items SET qty = ? WHERE user_id = ? AND product_id = ?",
                   (max(1, min(qty, limit)), g.user["id"], pid))
    return redirect(url_for("shop.cart"))


@bp.post("/checkout")
@login_required
def checkout():
    db, uid = get_db(), g.user["id"]
    address = " ".join((request.form.get("address") or "").split())
    if not 5 <= len(address) <= 200:
        flash("Укажите адрес доставки: от 5 до 200 символов.", "error")
        return redirect(url_for("shop.cart"))
    try:
        with transaction(db):
            rows = _cart_rows(db, uid)
            if not rows:
                flash("Корзина пуста.", "error")
                return redirect(url_for("shop.cart"))
            total = sum(r["price"] * r["qty"] for r in rows)
            oid = db.execute("INSERT INTO orders(user_id, total, address, created_at) VALUES (?,?,?,?)",
                             (uid, total, address, time.time())).lastrowid
            for r in rows:
                if db.execute("UPDATE products SET stock = stock - ? WHERE id = ? AND (stock IS NULL OR stock >= ?)",
                              (r["qty"], r["id"], r["qty"])).rowcount != 1:
                    raise OutOfStock(r["name"])
                db.execute("INSERT INTO order_items(order_id, product_id, name, icon, price, qty) VALUES (?,?,?,?,?,?)",
                           (oid, r["id"], r["name"], r["icon"], r["price"], r["qty"]))
            wallet.apply(db, uid, -total, "purchase", f"Заказ №{oid}")
            db.execute("DELETE FROM cart_items WHERE user_id = ?", (uid,))
    except wallet.InsufficientFunds:
        flash("Не хватает зачёток. Загляните в игры — там можно пополнить баланс.", "error")
        return redirect(url_for("shop.cart"))
    except OutOfStock as e:
        flash(f"«{e}» только что закончился. Обновите количество в корзине.", "error")
        return redirect(url_for("shop.cart"))
    current_app.logger.info("order id=%s user=%s total=%s", oid, uid, total)
    flash("Заказ оформлен. Курьер вышел. Вернётся ли — вопрос.", "ok")
    return redirect(url_for("shop.order", oid=oid))


@bp.get("/orders")
@login_required
def orders():
    rows = get_db().execute("SELECT o.*, (SELECT COALESCE(SUM(qty), 0) FROM order_items WHERE order_id = o.id) AS items "
                            "FROM orders o WHERE user_id = ? ORDER BY id DESC", (g.user["id"],)).fetchall()
    return render_template("shop/orders.html", rows=rows)


@bp.get("/orders/<int:oid>")
@login_required
def order(oid):
    db = get_db()
    o = db.execute("SELECT * FROM orders WHERE id = ? AND user_id = ?", (oid, g.user["id"])).fetchone()
    if o is None:
        abort(404)
    step, last = max(1, current_app.config["DELIVERY_STEP_SECONDS"]), len(TRACK) - 1
    idx = last if o["status"] != "delivering" else min(int((time.time() - o["created_at"]) // step), last)
    if idx == last and o["status"] == "delivering":
        with transaction(db):
            if db.execute("UPDATE orders SET status = 'delivered', finished_at = ? WHERE id = ? AND status = 'delivering'",
                          (time.time(), oid)).rowcount == 1:
                _pay_sellers(db, oid)
        o = db.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
    items = db.execute("SELECT * FROM order_items WHERE order_id = ?", (oid,)).fetchall()
    return render_template("shop/order.html", o=o, items=items, track=TRACK, idx=idx,
                           live=step if idx < last else 0)


# ───────── отзывы: правка, удаление, «полезно» ─────────


def _review_back(r):
    return redirect(url_for("shop.product", pid=r["product_id"]) + "#reviews")


def _my_review(db, rid):
    r = db.execute("SELECT * FROM reviews WHERE id = ? AND user_id = ?", (rid, g.user["id"])).fetchone()
    if r is None:
        abort(404)
    return r


@bp.post("/review/<int:rid>/edit")
@login_required
def review_edit(rid):
    db = get_db(); r = _my_review(db, rid)
    rating, body = request.form.get("rating", type=int), (request.form.get("body") or "").strip()
    if rating not in range(1, 6) or not 5 <= len(body) <= 500:
        flash("Оценка от 1 до 5 и текст от 5 до 500 символов.", "error")
    else:
        db.execute("UPDATE reviews SET rating = ?, body = ? WHERE id = ?", (rating, body, rid))
        flash("Отзыв обновлён.", "ok")
    return _review_back(r)


@bp.post("/review/<int:rid>/delete")
@login_required
def review_delete(rid):
    db = get_db(); r = _my_review(db, rid)
    db.execute("DELETE FROM reviews WHERE id = ?", (rid,))
    flash("Отзыв удалён.", "ok")
    return _review_back(r)


@bp.post("/review/<int:rid>/helpful")
@login_required
def review_helpful(rid):
    db = get_db()
    r = db.execute("SELECT * FROM reviews WHERE id = ?", (rid,)).fetchone()
    if r is None:
        abort(404)
    if r["user_id"] == g.user["id"]:
        flash("Свой отзыв отмечать нельзя.", "error")
    elif db.execute("DELETE FROM review_votes WHERE review_id = ? AND user_id = ?", (rid, g.user["id"])).rowcount == 0:
        db.execute("INSERT INTO review_votes(review_id, user_id) VALUES (?,?)", (rid, g.user["id"]))
    return _review_back(r)


# ───────── живой поиск ─────────


@bp.get("/api/suggest")
def suggest():
    q = (request.args.get("q") or "").strip()[:60]
    if len(q) < 2:
        return jsonify(ok=True, items=[])
    like = "%" + q.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = get_db().execute("SELECT id, name, icon, price FROM products WHERE is_active = 1 AND status = 'approved' "
                            "AND casefold(name) LIKE ? ESCAPE '\\' ORDER BY name LIMIT 6", (like,)).fetchall()
    return jsonify(ok=True, items=[dict(r) for r in rows])


# ───────── отмена, повтор заказа, выплаты продавцам ─────────

COMMISSION = 0.10


def _pay_sellers(db, oid):
    """Продавцы получают выручку (за вычетом комиссии) только когда заказ доставлен."""
    rows = db.execute("SELECT p.seller_id AS sid, SUM(oi.price * oi.qty) AS s FROM order_items oi "
                      "JOIN products p ON p.id = oi.product_id WHERE oi.order_id = ? AND p.seller_id IS NOT NULL "
                      "GROUP BY p.seller_id", (oid,)).fetchall()
    for r in rows:
        wallet.apply(db, r["sid"], int(r["s"] * (1 - COMMISSION)), "sale", f"Заказ №{oid}")


@bp.post("/orders/<int:oid>/cancel")
@login_required
def order_cancel(oid):
    db = get_db()
    step = max(1, current_app.config["DELIVERY_STEP_SECONDS"])
    with transaction(db):
        o = db.execute("SELECT * FROM orders WHERE id = ? AND user_id = ?", (oid, g.user["id"])).fetchone()
        if o is None:
            abort(404)
        if o["status"] != "delivering" or time.time() - o["created_at"] >= step * (len(TRACK) - 1):
            flash("Этот заказ уже нельзя отменить: курьер дошёл (или потерялся окончательно).", "error")
            return redirect(url_for("shop.order", oid=oid))
        db.execute("UPDATE orders SET status = 'cancelled', finished_at = ? WHERE id = ?", (time.time(), oid))
        for i in db.execute("SELECT * FROM order_items WHERE order_id = ?", (oid,)).fetchall():
            db.execute("UPDATE products SET stock = stock + ? WHERE id = ? AND stock IS NOT NULL", (i["qty"], i["product_id"]))
        wallet.apply(db, g.user["id"], o["total"], "refund", f"Отмена заказа №{oid}")
    flash(f"Заказ отменён, {o['total']} зачёток вернулись на баланс.", "ok")
    return redirect(url_for("shop.order", oid=oid))


@bp.post("/orders/<int:oid>/repeat")
@login_required
def order_repeat(oid):
    db = get_db()
    if not db.execute("SELECT 1 FROM orders WHERE id = ? AND user_id = ?", (oid, g.user["id"])).fetchone():
        abort(404)
    added = 0
    for i in db.execute("SELECT * FROM order_items WHERE order_id = ?", (oid,)).fetchall():
        p = db.execute("SELECT * FROM products WHERE id = ? AND is_active = 1 AND status = 'approved'", (i["product_id"],)).fetchone()
        if p and (p["stock"] is None or p["stock"] > 0):
            qty = min(i["qty"], 20, p["stock"] if p["stock"] is not None else 20)
            db.execute("INSERT INTO cart_items(user_id, product_id, qty) VALUES (?,?,?) "
                       "ON CONFLICT(user_id, product_id) DO UPDATE SET qty = excluded.qty", (g.user["id"], p["id"], qty))
            added += 1
    flash(f"Товаров добавлено в корзину: {added}." if added else "Ничего из этого заказа сейчас нет в продаже.", "ok" if added else "error")
    return redirect(url_for("shop.cart"))


# ───────── «пульс» рынка: живые данные для главной и бегущей строки ─────────


def _pulse(db):
    now = time.time()
    window = max(1, current_app.config["DELIVERY_STEP_SECONDS"]) * len(TRACK)
    row = db.execute("SELECT (SELECT COUNT(*) FROM orders WHERE status = 'delivering' AND created_at > ?) AS ontheway, "
                     "(SELECT COUNT(*) FROM orders WHERE status != 'cancelled' AND created_at > ?) AS today, "
                     "(SELECT COUNT(*) FROM users) AS users", (now - window, now - 86400)).fetchone()
    top = db.execute("SELECT oi.product_id AS id, oi.name FROM order_items oi JOIN orders o ON o.id = oi.order_id "
                     "WHERE o.status != 'cancelled' AND o.created_at > ? GROUP BY oi.name ORDER BY SUM(oi.qty) DESC, oi.name LIMIT 1",
                     (now - 7 * 86400,)).fetchone()
    return {**dict(row), "top": dict(top) if top else None}


@bp.get("/api/pulse")
def pulse():
    db = get_db()
    recent = db.execute("SELECT oi.name, oi.qty FROM order_items oi JOIN orders o ON o.id = oi.order_id "
                        "WHERE o.status != 'cancelled' ORDER BY oi.id DESC LIMIT 5").fetchall()
    return jsonify(ok=True, **_pulse(db), recent=[dict(r) for r in recent])
