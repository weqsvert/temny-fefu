"""Капча на сервере.

Ответ хранится в базе, а не в cookie: иначе старую cookie можно было бы подсунуть
повторно. Каждая капча одноразовая: любая попытка (верная или нет) сжигает её.
"""
import hmac
import io
import math
import random
import secrets
import time

from flask import Blueprint, abort, jsonify, request, send_file
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .db import get_db
from .security import client_ip, rate_hit, rate_limited

bp = Blueprint("captcha", __name__, url_prefix="/captcha")

TTL = 600  # секунд
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # без I, O, 0, 1: их путают
LENGTH = 5
WIDTH, HEIGHT = 230, 76

_FONT_CANDIDATES = (
    "DejaVuSansMono-Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationMono-Bold.ttf",
    "Consolas.ttf", "consolab.ttf", "Menlo.ttc", "Arial Bold.ttf", "arialbd.ttf",
)
_WORDS = ("зачётка", "курьер", "сессия", "автомат", "общага", "пересдача", "деканат", "матанализ")
_font_cache = {}


def _font(size: int):
    if size not in _font_cache:
        for name in _FONT_CANDIDATES:
            try:
                _font_cache[size] = ImageFont.truetype(name, size)
                break
            except OSError:
                continue
        else:
            _font_cache[size] = ImageFont.load_default(size=size)
    return _font_cache[size]


def _question():
    rnd = random.SystemRandom()
    kind = rnd.choice(("minus", "times", "letters", "plus"))
    if kind == "minus":
        a, b = rnd.randint(12, 40), rnd.randint(3, 11)
        return f"У вас {a} зачёток. Курьер потерял {b}. Сколько осталось?", str(a - b)
    if kind == "times":
        a, b = rnd.randint(3, 9), rnd.randint(3, 9)
        return f"Сколько будет {a} × {b}?", str(a * b)
    if kind == "plus":
        a, b = rnd.randint(11, 49), rnd.randint(11, 49)
        return f"Курьер прошёл {a} шагов, потом ещё {b}. Сколько шагов всего?", str(a + b)
    word = rnd.choice(_WORDS)
    return f"Сколько букв в слове «{word}»?", str(len(word))


def new_captcha(db, kind: str = "image") -> dict:
    """Создаёт капчу и возвращает то, что можно показывать пользователю."""
    now = time.time()
    db.execute("DELETE FROM captchas WHERE expires_at < ?", (now,))
    cid = secrets.token_urlsafe(12)
    if kind == "question":
        prompt, answer = _question()
    else:
        kind, prompt = "image", ""
        answer = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
    db.execute(
        "INSERT INTO captchas(id, answer, kind, prompt, expires_at) VALUES (?,?,?,?,?)",
        (cid, answer, kind, prompt, now + TTL),
    )
    return {"id": cid, "kind": kind, "prompt": prompt}


def verify(db, captcha_id, answer) -> bool:
    """Проверяет и сжигает капчу."""
    if not captcha_id or not isinstance(captcha_id, str) or len(captcha_id) > 64:
        return False
    row = db.execute("SELECT answer, expires_at FROM captchas WHERE id = ?", (captcha_id,)).fetchone()
    if row is None:
        return False
    burned = db.execute("DELETE FROM captchas WHERE id = ?", (captcha_id,)).rowcount
    if burned != 1 or row["expires_at"] < time.time():
        return False
    given = (answer or "").strip().casefold()
    return hmac.compare_digest(given.encode(), row["answer"].casefold().encode())


def render_png(code: str, seed: str) -> bytes:
    rnd = random.Random(seed)  # картинка стабильна для одного id
    img = Image.new("RGB", (WIDTH, HEIGHT), (21, 19, 31))
    draw = ImageDraw.Draw(img)

    for _ in range(260):  # шум
        x, y = rnd.randrange(WIDTH), rnd.randrange(HEIGHT)
        c = rnd.randint(40, 90)
        draw.point((x, y), fill=(c, c, c + 25))

    palette = [(198, 255, 61), (143, 123, 255), (255, 61, 129), (235, 233, 246)]
    step = (WIDTH - 36) / len(code)
    for i, ch in enumerate(code):
        size = rnd.randint(40, 48)
        tile = Image.new("RGBA", (size + 24, size + 24), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((10, 2), ch, font=_font(size), fill=rnd.choice(palette) + (255,))
        tile = tile.rotate(rnd.uniform(-28, 28), resample=Image.BICUBIC, expand=True)
        x = int(18 + i * step + rnd.randint(-3, 3))
        y = int((HEIGHT - tile.height) / 2 + rnd.randint(-5, 5))
        img.paste(tile, (x, y), tile)

    draw = ImageDraw.Draw(img)
    for _ in range(4):  # перечёркивающие линии
        pts = [(rnd.randrange(WIDTH), rnd.randrange(HEIGHT)) for _ in range(3)]
        draw.line(pts, fill=rnd.choice(palette), width=rnd.choice((1, 2)))

    # лёгкая волна по вертикали
    src = img.copy()
    amp, period = rnd.uniform(2.0, 3.5), rnd.uniform(30, 48)
    for x in range(WIDTH):
        dy = int(amp * math.sin(2 * math.pi * x / period))
        img.paste(src.crop((x, 0, x + 1, HEIGHT)), (x, dy))
    img = img.filter(ImageFilter.GaussianBlur(0.6))

    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


@bp.get("/new")
def api_new():
    db = get_db()
    ip = client_ip()
    if rate_limited(db, f"captcha:{ip}", 40, 600):
        return jsonify(ok=False, error="Слишком часто. Подождите минуту."), 429
    rate_hit(db, f"captcha:{ip}")
    kind = "question" if request.args.get("kind") == "question" else "image"
    return jsonify(ok=True, **new_captcha(db, kind))


@bp.get("/<cid>.png")
def image(cid):
    row = get_db().execute(
        "SELECT answer, kind, expires_at FROM captchas WHERE id = ?", (cid[:64],)
    ).fetchone()
    if row is None or row["kind"] != "image" or row["expires_at"] < time.time():
        abort(404)
    resp = send_file(io.BytesIO(render_png(row["answer"], cid)), mimetype="image/png")
    resp.headers["Cache-Control"] = "no-store"
    return resp
