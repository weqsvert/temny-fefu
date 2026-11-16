"""Продавцы: свои товары, остатки, модерация администратором."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .audit import log_event
from .db import get_db
from .security import admin_required, login_required

bp = Blueprint("sell", __name__)


def _admin() -> bool:
    return g.user["role"] == "admin"


def _need_seller():
    if not (g.user["is_seller"] or _admin()):
        abort(403, description="Сначала станьте продавцом на странице «Продажи».")


def _product(pid):
    p = get_db().execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    if p is None or not (_admin() or p["seller_id"] == g.user["id"]):
        abort(404)
    return p


def _home():
    return redirect(url_for("sell.admin_list" if request.form.get("from") == "admin" else "sell.index"))


def _list(where, args, admin, locked=False):
    rows = [] if locked else get_db().execute(
        f"SELECT p.*, u.username AS seller FROM products p LEFT JOIN users u ON u.id = p.seller_id WHERE {where} "
        "ORDER BY (p.status = 'pending') DESC, p.id DESC", args).fetchall()
    return render_template("sell.html", rows=rows, admin=admin, locked=locked)


@bp.get("/sell")
@login_required
def index():
    if not (g.user["is_seller"] or _admin()):
        return _list("", (), False, locked=True)
    return _list("p.seller_id = ?", (g.user["id"],), False)


@bp.get("/admin/products")
@admin_required
def admin_list():
    return _list("1 = 1", (), True)


@bp.post("/sell/become")
@login_required
def become():
    get_db().execute("UPDATE users SET is_seller = 1 WHERE id = ?", (g.user["id"],))
    log_event("became_seller", user=g.user)
    flash("Теперь вы продавец. Добавьте первый товар.", "ok")
    return redirect(url_for("sell.index"))


def _parse(form):
    f = {k: (form.get(k) or "").strip() for k in ("name", "icon", "category", "description", "price", "stock")}
    f["icon"] = f["icon"][:8] or "📦"
    price = int(f["price"]) if f["price"].isdigit() else 0
    stock = None if f["stock"] == "" else (int(f["stock"]) if f["stock"].isdigit() else -1)
    err = None
    if not 3 <= len(f["name"]) <= 80:
        err = "Название: от 3 до 80 символов."
    elif not 2 <= len(f["category"]) <= 30:
        err = "Категория: от 2 до 30 символов."
    elif len(f["description"]) > 300:
        err = "Описание: не длиннее 300 символов."
    elif not 1 <= price <= 1_000_000:
        err = "Цена: целое число от 1 до 1 000 000."
    elif stock is not None and not 0 <= stock <= 9999:
        err = "Остаток: число от 0 до 9999 или пусто (без ограничений)."
    return f, price, stock, err


@bp.route("/sell/new", methods=("GET", "POST"))
@bp.route("/sell/<int:pid>/edit", methods=("GET", "POST"))
@login_required
def edit(pid=None):
    _need_seller()
    db = get_db()
    p = _product(pid) if pid else None
    form, err = (dict(p) if p else {"icon": "📦", "stock": ""}), None
    if p and p["stock"] is None:
        form["stock"] = ""
    if request.method == "POST":
        form, price, stock, err = _parse(request.form)
        if not err:
            # администратор публикует сразу; товары продавцов уходят на проверку
            status = (p["status"] if p else "approved") if _admin() else "pending"
            vals = (form["name"], form["icon"], form["category"], form["description"], price, stock, status)
            if p:
                db.execute("UPDATE products SET name=?, icon=?, category=?, description=?, price=?, stock=?, status=? WHERE id=?",
                           (*vals, p["id"]))
            else:
                import time
                db.execute("INSERT INTO products(name, icon, category, description, price, stock, status, seller_id, created_at) "
                           "VALUES (?,?,?,?,?,?,?,?,?)", (*vals, g.user["id"], time.time()))
            log_event("product_saved", user=g.user, details=form["name"])
            flash("Товар сохранён." if status == "approved" else "Товар отправлен на проверку администратору.", "ok")
            return redirect(url_for("sell.index"))
    cats = [r[0] for r in db.execute("SELECT DISTINCT category FROM products ORDER BY category")]
    return render_template("product_form.html", form=form, error=err, editing=p, cats=cats)


@bp.post("/sell/<int:pid>/toggle")
@login_required
def toggle(pid):
    _need_seller(); p = _product(pid)
    get_db().execute("UPDATE products SET is_active = 1 - is_active WHERE id = ?", (p["id"],))
    flash("Товар скрыт." if p["is_active"] else "Товар снова виден.", "ok")
    return _home()


@bp.post("/sell/<int:pid>/restock")
@login_required
def restock(pid):
    _need_seller(); p = _product(pid)
    n = request.form.get("amount", type=int)
    if p["stock"] is None:
        flash("У этого товара остаток не ограничен.", "error")
    elif n is None or not 1 <= n <= 9999 or p["stock"] + n > 9999:
        flash("Добавьте от 1 до 9999 штук (всего не больше 9999).", "error")
    else:
        get_db().execute("UPDATE products SET stock = stock + ? WHERE id = ?", (n, p["id"]))
        flash(f"Остаток пополнен на {n}.", "ok")
    return _home()


@bp.post("/sell/<int:pid>/moderate")
@admin_required
def moderate(pid):
    verdict = "approved" if request.form.get("verdict") == "approve" else "rejected"
    p = _product(pid)
    get_db().execute("UPDATE products SET status = ? WHERE id = ?", (verdict, p["id"]))
    log_event("product_" + verdict, user=g.user, details=p["name"])
    flash("Товар одобрен." if verdict == "approved" else "Товар отклонён.", "ok")
    return redirect(url_for("sell.admin_list"))
