"""ТёмныйФефу — динамический маркетплейс-пародия на Flask + SQLite."""
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

import click
from flask import Flask, g, jsonify, render_template, request, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from . import db as database
from . import security
from .security import csrf_token, wants_json

SYSTEM_MESSAGES = [
    "Подключение через 14 прокси… ошибка: нет денег на балансе.",
    "Курьер найден. Курьер потерян.",
    "Wi-Fi в корпусе не обнаружен. Но вы это и так знали.",
    "Горячая вода: не найдена. Холодная: в наличии.",
    "Курьер найден на нижних этажах корпуса E.",
    "Автобус от кампуса заполнен. Следующий тоже.",
    "Корпус E: вы находитесь здесь. Выход не найден.",
    "Курс зачётки упал: 1 зачётка = 3 бессонные ночи.",
]


def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _load_or_create_secret(instance: Path) -> str:
    """В режиме разработки ключ создаётся один раз и лежит в instance/secret_key."""
    path = instance / "secret_key"
    if path.exists():
        return path.read_text().strip()
    key = secrets.token_hex(32)
    path.write_text(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def _setup_logging(app: Flask, instance: Path):
    log_dir = instance / "logs"
    log_dir.mkdir(exist_ok=True)
    handler = RotatingFileHandler(log_dir / "fefu.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    handler.setLevel(logging.INFO)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)


def plural(n, forms):
    n = abs(int(n))
    if 11 <= n % 100 <= 14:
        return forms[2]
    last = n % 10
    if last == 1:
        return forms[0]
    return forms[1] if 2 <= last <= 4 else forms[2]


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    instance = Path(app.instance_path)
    instance.mkdir(parents=True, exist_ok=True)

    prod = os.environ.get("FEFU_ENV", "development").lower() == "production"
    secret = os.environ.get("SECRET_KEY")
    if prod and not secret:
        raise RuntimeError("В production обязательно задайте переменную SECRET_KEY.")

    app.config.update(
        IS_PRODUCTION=prod,
        SECRET_KEY=secret or _load_or_create_secret(instance),
        DATABASE=str(instance / "fefu.sqlite3"),
        SESSION_COOKIE_NAME="fefu_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=prod,
        PERMANENT_SESSION_LIFETIME=timedelta(days=14),
        MAX_CONTENT_LENGTH=64 * 1024,
        JSON_AS_ASCII=False,
        START_BALANCE=400,
        DELIVERY_STEP_SECONDS=int(os.environ.get("DELIVERY_STEP_SECONDS", "12")),
        CAPTCHA_ON_LOGIN=os.environ.get("CAPTCHA_ON_LOGIN", "adaptive"),  # always | adaptive | never
        CAPTCHA_AFTER_FAILS=3,
        LOGIN_LOCK_AFTER=5,
        LOGIN_LOCK_SECONDS=900,
        LOGIN_IP_FAIL_LIMIT=30,
        RESET_TOKEN_TTL=1800,
        DEV_OUTBOX=_env_bool("DEV_OUTBOX", not prod),
        SMTP_HOST=os.environ.get("SMTP_HOST", ""),
        SMTP_PORT=int(os.environ.get("SMTP_PORT", "587")),
        SMTP_USER=os.environ.get("SMTP_USER", ""),
        SMTP_PASSWORD=os.environ.get("SMTP_PASSWORD", ""),
        SMTP_TLS=_env_bool("SMTP_TLS", True),
        MAIL_FROM=os.environ.get("MAIL_FROM", "ТёмныйФефу <no-reply@temny-fefu.local>"),
        APP_TZ=os.environ.get("APP_TZ", "Asia/Vladivostok"),
        SYSTEM_MESSAGES=SYSTEM_MESSAGES,
    )
    if test_config:
        app.config.update(test_config)

    if _env_bool("TRUST_PROXY"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    if not app.testing:
        _setup_logging(app, instance)

    database.init_app(app)
    security.init_app(app)
    _register_template_helpers(app)
    _register_errors(app)

    from . import account, admin, auth, captcha, games, sell, shop, wallet_page
    for module in (auth, shop, games, account, admin, captcha, sell, wallet_page):
        app.register_blueprint(module.bp)

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok")

    _register_cli(app)

    with app.app_context():
        database.init_db()
        from .seed import seed_if_empty
        seed_if_empty(database.get_db())
        _bootstrap_admin(app)

    return app


def _register_template_helpers(app: Flask):
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(app.config["APP_TZ"])
    except Exception:  # нет tzdata (Windows) — берём часовой пояс системы
        tz = None

    @app.template_filter("num")
    def num(n):
        return f"{int(n):,}".replace(",", "\u202f")

    @app.template_filter("money")
    def money(n):
        return f"{num(n)}\u00a0{plural(n, ('зачётка', 'зачётки', 'зачёток'))}"

    @app.template_filter("signed")
    def signed(n):
        n = int(n)
        return f"{'+' if n > 0 else ''}{num(n)}".replace("-", "−")

    @app.template_filter("dt")
    def dt(ts, fmt="%d.%m.%Y %H:%M"):
        if not ts:
            return "—"
        moment = datetime.fromtimestamp(ts, tz) if tz else datetime.fromtimestamp(ts)
        return moment.strftime(fmt)

    @app.template_filter("stars")
    def stars(value):
        n = max(0, min(5, int(round(float(value or 0)))))
        return "★" * n + "☆" * (5 - n)

    @app.template_filter("pl")
    def pl(n, one, few, many):
        return plural(n, (one, few, many))

    @app.template_global()
    def page_url(n):
        """Адрес текущей страницы с другим номером страницы (фильтры сохраняются)."""
        args = {**(request.view_args or {}), **{k: v for k, v in request.args.items() if k != "page"}, "page": n}
        return url_for(request.endpoint, **args)

    @app.context_processor
    def inject():
        cart_count = 0
        if g.get("user"):
            cart_count = database.get_db().execute(
                "SELECT COALESCE(SUM(qty), 0) FROM cart_items WHERE user_id = ?", (g.user["id"],)
            ).fetchone()[0]
        return {
            "csrf_token": csrf_token,
            "current_user": g.get("user"),
            "cart_count": cart_count,
            "system_messages": app.config["SYSTEM_MESSAGES"],
            "dev_outbox": app.config["DEV_OUTBOX"],
        }


_ERRORS = {
    400: ("Запрос отклонён", "Что-то пошло не так с запросом. Обновите страницу и попробуйте снова."),
    401: ("Нужен вход", "Войдите в аккаунт, чтобы продолжить."),
    403: ("Доступ закрыт", "У вас нет прав на эту страницу. Даже в даркнете есть вход только для своих."),
    404: ("Не найдено", "Такой страницы нет. Возможно, она в корпусе E, а оттуда не возвращаются."),
    405: ("Так нельзя", "Для этой страницы такой способ запроса не подходит."),
    413: ("Слишком большой запрос", "Сократите отправляемые данные и повторите."),
    429: ("Слишком много попыток", "Подождите немного и попробуйте ещё раз."),
    500: ("Сбой системы", "Что-то сломалось на нашей стороне. Мы уже в курсе — загляните позже."),
}


def _register_errors(app: Flask):
    def handle(exc):
        code = exc.code if isinstance(exc, HTTPException) else 500
        title, text = _ERRORS.get(code, ("Ошибка", "Что-то пошло не так."))
        custom = getattr(exc, "description", None)
        if isinstance(exc, HTTPException) and custom and custom != type(exc).description:
            text = custom
        if wants_json():
            return jsonify(ok=False, error=text), code
        resp = app.make_response((render_template("error.html", code=code, title=title, text=text), code))
        if code == 429:
            resp.headers["Retry-After"] = "60"
        return resp

    for code in _ERRORS:
        app.register_error_handler(code, handle)


def _bootstrap_admin(app: Flask):
    """Создаёт администратора из переменных окружения, если его ещё нет."""
    import sqlite3
    from .accounts import create_user
    name = os.environ.get("ADMIN_USERNAME")
    email = os.environ.get("ADMIN_EMAIL")
    password = os.environ.get("ADMIN_PASSWORD")
    if not (name and email and password):
        return
    db = database.get_db()
    if db.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone():
        return
    try:
        create_user(db, name, email, password, role="admin")
        app.logger.info("Создан администратор %s", name)
    except sqlite3.IntegrityError:
        app.logger.warning("Не удалось создать администратора: имя или почта заняты.")


def _register_cli(app: Flask):
    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.option("--email", prompt=True)
    @click.password_option()
    def create_admin(username, email, password):
        """Создать администратора."""
        import sqlite3
        from .accounts import create_user
        problem = (
            security.validate_username(security.normalize_username(username))
            or security.validate_email(email.strip().lower())
            or security.validate_password(password, username, email)
        )
        if problem:
            raise click.ClickException(problem)
        try:
            create_user(database.get_db(), security.normalize_username(username),
                        email.strip().lower(), password, role="admin")
        except sqlite3.IntegrityError:
            raise click.ClickException("Имя или почта уже заняты.")
        click.echo(f"Администратор {username} создан.")

    @app.cli.command("init-db")
    def init_db_cmd():
        """Создать таблицы и наполнить каталог."""
        from .seed import seed_if_empty
        database.init_db()
        click.echo("Каталог наполнен." if seed_if_empty(database.get_db()) else "База уже готова.")
