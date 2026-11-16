-- Схема ТёмногоФефу. Все операции идемпотентны (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS users (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  username        TEXT    NOT NULL,                 -- как показываем
  username_key    TEXT    NOT NULL UNIQUE,          -- нормализованный (регистр, похожие буквы)
  email           TEXT    NOT NULL UNIQUE,          -- всегда в нижнем регистре
  password_hash   TEXT    NOT NULL,
  role            TEXT    NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
  balance         INTEGER NOT NULL DEFAULT 0 CHECK (balance >= 0),
  is_active       INTEGER NOT NULL DEFAULT 1,
  is_seller       INTEGER NOT NULL DEFAULT 0,
  session_version INTEGER NOT NULL DEFAULT 1,       -- увеличиваем => все сессии аннулируются
  failed_logins   INTEGER NOT NULL DEFAULT 0,
  locked_until    REAL    NOT NULL DEFAULT 0,
  created_at      REAL    NOT NULL,
  last_login_at   REAL
);

CREATE TABLE IF NOT EXISTS products (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT    NOT NULL,
  icon        TEXT    NOT NULL DEFAULT '📦',
  category    TEXT    NOT NULL,
  description TEXT    NOT NULL DEFAULT '',
  price       INTEGER NOT NULL CHECK (price >= 0),
  stock       INTEGER CHECK (stock IS NULL OR stock >= 0),   -- NULL = без ограничений
  is_active   INTEGER NOT NULL DEFAULT 1,
  seller_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,   -- NULL = продаёт сам магазин
  status      TEXT    NOT NULL DEFAULT 'approved' CHECK (status IN ('approved', 'pending', 'rejected')),
  created_at  REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_products_category ON products(category);

CREATE TABLE IF NOT EXISTS reviews (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,   -- NULL у стартовых отзывов
  author     TEXT    NOT NULL,
  rating     INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
  body       TEXT    NOT NULL,
  created_at REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_reviews_product ON reviews(product_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_reviews_user_product
  ON reviews(product_id, user_id) WHERE user_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS cart_items (
  user_id    INTEGER NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  qty        INTEGER NOT NULL CHECK (qty BETWEEN 1 AND 20),
  PRIMARY KEY (user_id, product_id)
);

CREATE TABLE IF NOT EXISTS orders (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  total       INTEGER NOT NULL,
  status      TEXT    NOT NULL DEFAULT 'delivering'
              CHECK (status IN ('delivering', 'delivered', 'cancelled')),
  address     TEXT    NOT NULL,
  created_at  REAL    NOT NULL,
  finished_at REAL
);
CREATE INDEX IF NOT EXISTS ix_orders_user ON orders(user_id, id DESC);

CREATE TABLE IF NOT EXISTS order_items (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id   INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
  name       TEXT    NOT NULL,      -- снимок на момент покупки
  icon       TEXT    NOT NULL,
  price      INTEGER NOT NULL,
  qty        INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_order_items_order ON order_items(order_id);

-- Журнал движения зачёток: каждое изменение баланса оставляет след.
CREATE TABLE IF NOT EXISTS wallet_tx (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  amount        INTEGER NOT NULL,
  balance_after INTEGER NOT NULL,
  kind          TEXT    NOT NULL,
  note          TEXT    NOT NULL DEFAULT '',
  created_at    REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_wallet_user ON wallet_tx(user_id, id DESC);

CREATE TABLE IF NOT EXISTS game_state (
  user_id            INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  last_collect       REAL NOT NULL,
  last_mine          REAL NOT NULL DEFAULT 0,
  bus_started        REAL NOT NULL DEFAULT 0,
  bus_cooldown_until REAL NOT NULL DEFAULT 0,
  last_spin          REAL NOT NULL DEFAULT 0,
  daily_streak       INTEGER NOT NULL DEFAULT 0,
  last_daily         REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_upgrades (
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  upgrade_key TEXT    NOT NULL,
  owned       INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, upgrade_key)
);

-- В базе лежит только хеш токена: утечка БД не даёт ссылок для сброса пароля.
CREATE TABLE IF NOT EXISTS password_resets (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash TEXT    NOT NULL UNIQUE,
  expires_at REAL    NOT NULL,
  used_at    REAL,
  created_at REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS captchas (
  id         TEXT PRIMARY KEY,
  answer     TEXT NOT NULL,
  kind       TEXT NOT NULL DEFAULT 'image',
  prompt     TEXT NOT NULL DEFAULT '',
  expires_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS rate_events (
  key TEXT NOT NULL,
  ts  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rate_key_ts ON rate_events(key, ts);

-- Журнал событий. Без внешнего ключа: записи переживают удаление аккаунта.
CREATE TABLE IF NOT EXISTS audit_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  ts         REAL    NOT NULL,
  user_id    INTEGER,
  username   TEXT,
  event      TEXT    NOT NULL,
  ip         TEXT,
  user_agent TEXT,
  details    TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_audit_user ON audit_log(user_id, id DESC);
CREATE INDEX IF NOT EXISTS ix_audit_event ON audit_log(event, id DESC);

-- «Исходящая почта» для режима разработки (SMTP не обязателен).
CREATE TABLE IF NOT EXISTS outbox (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  to_addr    TEXT NOT NULL,
  subject    TEXT NOT NULL,
  body       TEXT NOT NULL,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS review_votes (
  review_id INTEGER NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
  user_id   INTEGER NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
  PRIMARY KEY (review_id, user_id)
);
