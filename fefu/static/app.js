(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const csrf = () => $('meta[name="csrf"]')?.content || "";
  const fmt = n => Number(n).toLocaleString("ru-RU");

  async function api(url, body) {
    const opt = { headers: { "X-Requested-With": "fetch", "X-CSRF-Token": csrf() } };
    if (body !== undefined) { opt.method = "POST"; opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    try {
      const r = await fetch(url, opt);
      const data = await r.json().catch(() => ({ ok: false, error: "Сервер ответил непонятно." }));
      return { ...data, status: r.status };
    } catch { return { ok: false, status: 0, error: "Нет связи с сервером." }; }
  }
  function toast(text, error = false) {
    const el = document.createElement("div");
    el.className = "toast" + (error ? " toast--error" : "");
    el.textContent = text;
    $("#toasts").append(el);
    setTimeout(() => el.remove(), 4500);
  }

  // шапка, уведомления, лента сообщений
  const toggle = $(".menu-toggle");
  toggle?.addEventListener("click", () => toggle.setAttribute("aria-expanded", $("#nav").classList.toggle("is-open")));
  document.addEventListener("click", e => {
    if (e.target.closest("[data-close]")) e.target.closest(".flash").remove();
    const q = e.target.closest("[data-qty]");
    if (q) { const i = q.parentElement.querySelector("input"); i.value = Math.max(1, Math.min(20, (+i.value || 1) + +q.dataset.qty)); }
    const pw = e.target.closest("[data-pw]");
    if (pw) { const i = pw.previousElementSibling; i.type = i.type === "password" ? "text" : "password"; pw.textContent = i.type === "password" ? "показать" : "скрыть"; }
    const cap = e.target.closest("[data-captcha-new]");
    if (cap) newCaptcha(cap.closest("[data-captcha]"), cap.dataset.captchaNew);
  });
  $$("[data-autosubmit]").forEach(s => s.addEventListener("change", () => s.form.submit()));

  const feed = $(".feed__text");
  if (feed && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const msgs = JSON.parse(feed.dataset.messages || "[]");
    let i = 0;
    if (msgs.length > 1) setInterval(() => {
      feed.classList.add("is-fading");
      setTimeout(() => { feed.textContent = msgs[++i % msgs.length]; feed.classList.remove("is-fading"); }, 260);
    }, 6000);
  }

  // индикатор надёжности пароля
  const LABELS = ["", "слабый", "так себе", "неплохой", "крепкий"];
  $$("[data-meter]").forEach(inp => inp.addEventListener("input", () => {
    const v = inp.value;
    const lvl = !v ? 0 : Math.min(4, 1 + (v.length >= 8) + (v.length >= 12) + (/[a-zа-яё]/i.test(v) && /\d/.test(v) && /[^\w\s]|[A-ZА-ЯЁ]/.test(v)));
    const wrap = inp.closest(".field");
    wrap.querySelector(".meter").dataset.level = lvl;
    wrap.querySelector(".meter-label").textContent = LABELS[lvl];
  }));

  // капча: обновить картинку или переключить на вопрос
  async function newCaptcha(box, kind) {
    const r = await api("/captcha/new?kind=" + kind);
    if (!r.ok) return toast(r.error || "Не удалось обновить проверку.", true);
    box.querySelector('[name="captcha_id"]').value = r.id;
    box.querySelector('[name="captcha_kind"]').value = r.kind;
    const row = box.querySelector(".captcha__row");
    row.replaceChildren();
    if (r.kind === "image") {
      const img = new Image(230, 76); img.alt = "Символы на картинке"; img.src = `/captcha/${encodeURIComponent(r.id)}.png`; row.append(img);
    } else { const p = document.createElement("p"); p.className = "captcha__prompt"; p.textContent = r.prompt; row.append(p); }
    box.querySelector('[name="captcha_answer"]').value = "";
  }

  // страница заказа: пока курьер в пути, обновляем трекер
  const live = $("[data-live]");
  if (live) setTimeout(() => location.reload(), Math.max(3, +live.dataset.live) * 1000);

  // подтверждения опасных действий
  document.addEventListener("submit", e => { const m = e.target.dataset?.confirm; if (m && !confirm(m)) e.preventDefault(); });

  // добавление в корзину без перезагрузки
  const setCount = n => { const c = $(".chip__count"); if (c) { c.textContent = n; c.hidden = !n; } };
  document.addEventListener("submit", async e => {
    const f = e.target.closest("[data-cart-add]");
    if (!f) return;
    e.preventDefault();
    const btn = f.querySelector("button:not([type=button])"); btn.disabled = true;
    try {
      const r = await fetch(f.action, { method: "POST", body: new FormData(f), headers: { "X-Requested-With": "fetch", "X-CSRF-Token": csrf() } });
      const d = await r.json();
      if (r.status === 401 && d.login) { location.href = d.login + "?next=" + encodeURIComponent(location.pathname + location.search); return; }
      toast(d.message || d.error, !d.ok);
      if (d.ok) setCount(d.count);
    } catch { toast("Нет связи с сервером.", true); }
    finally { btn.disabled = false; }
  });

  // живой поиск с подсказками
  const sform = $(".search"), sinput = $("input", sform);
  const box = document.createElement("ul");
  box.className = "suggest"; box.id = "suggest"; box.hidden = true; box.setAttribute("role", "listbox");
  sform.append(box); sinput.setAttribute("autocomplete", "off"); sinput.setAttribute("aria-controls", "suggest");
  let timer, sel = -1;
  const closeSuggest = () => { box.hidden = true; sel = -1; };
  sinput.addEventListener("input", () => {
    clearTimeout(timer);
    const q = sinput.value.trim();
    if (q.length < 2) return closeSuggest();
    timer = setTimeout(async () => {
      const r = await api("/api/suggest?q=" + encodeURIComponent(q));
      if (sinput.value.trim() !== q) return;
      const items = (r.items || []).map(it => {
        const li = document.createElement("li"), a = document.createElement("a");
        li.setAttribute("role", "option"); a.href = "/p/" + it.id; a.textContent = `${it.icon} ${it.name} · ${fmt(it.price)}`;
        li.append(a); return li;
      });
      if (!items.length) { const li = document.createElement("li"); li.className = "suggest__empty"; li.textContent = "Ничего не нашлось"; items.push(li); }
      box.replaceChildren(...items); box.hidden = false; sel = -1;
    }, 200);
  });
  sinput.addEventListener("keydown", e => {
    const links = $$("a", box);
    if (box.hidden || !links.length) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault(); sel = (sel + (e.key === "ArrowDown" ? 1 : -1) + links.length) % links.length;
      links.forEach((a, i) => a.classList.toggle("is-active", i === sel));
    } else if (e.key === "Enter" && sel >= 0) { e.preventDefault(); location.href = links[sel].href; }
    else if (e.key === "Escape") closeSuggest();
  });
  document.addEventListener("click", e => { if (!e.target.closest(".search")) closeSuggest(); });
  document.addEventListener("keydown", e => {
    if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); sinput.focus(); }
  });

  // режим взлома
  const hackBtn = $("#hack-toggle"), root_el = document.documentElement;
  const store = { get: k => { try { return localStorage.getItem(k); } catch { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch {} } };
  const setHack = on => { root_el.classList.toggle("hack", on); hackBtn.setAttribute("aria-pressed", on); hackBtn.textContent = "Режим взлома: " + (on ? "вкл" : "выкл"); store.set("fefu-hack", on ? "1" : "0"); };
  setHack(store.get("fefu-hack") === "1");
  hackBtn.addEventListener("click", () => setHack(!root_el.classList.contains("hack")));

  // терминальная заставка: один раз за сессию, закрывается кликом или любой клавишей
  if (!sessionStorage.getItem("fefu-boot") && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    sessionStorage.setItem("fefu-boot", "1");
    const ov = document.createElement("div"), pre = document.createElement("pre");
    ov.className = "boot"; ov.append(pre); document.body.append(ov);
    const lines = ["> подключение через 14 прокси…", "> ошибка: нет денег на балансе", "> обход деканата… ок", "> поиск курьера… курьер потерян", "> добро пожаловать в ТёмныйФефу"];
    let i = 0;
    const done = () => { clearInterval(t); ov.classList.add("is-out"); setTimeout(() => ov.remove(), 400); };
    const t = setInterval(() => { if (i < lines.length) pre.textContent += lines[i++] + "\n"; else { clearInterval(t); setTimeout(done, 500); } }, 380);
    ov.addEventListener("click", done); document.addEventListener("keydown", done, { once: true });
  }

  // «пульс» рынка: ведомость на главной и бегущая строка с настоящими покупками
  const ticker = $(".ticker"), ledger = $("#pulse");
  if (ticker) {
    const base = JSON.parse(ticker.dataset.messages || "[]"), track = $(".ticker__track", ticker);
    let last = "";
    const draw = msgs => {
      const key = msgs.join("|"); if (key === last) return; last = key;
      const mk = hidden => msgs.map(m => { const s = document.createElement("span"); s.textContent = m; if (hidden) s.setAttribute("aria-hidden", "true"); return s; });
      track.replaceChildren(...mk(false), ...mk(true));
    };
    const setPulse = (k, v) => {
      const el = ledger?.querySelector(`[data-pulse="${k}"]`);
      if (el && el.textContent !== String(v)) { el.textContent = v; el.classList.remove("is-new"); void el.offsetWidth; el.classList.add("is-new"); }
    };
    const pulse = async () => {
      if (document.hidden) return;
      const r = await api("/api/pulse"); if (!r.ok) return;
      setPulse("ontheway", r.ontheway); setPulse("today", r.today); setPulse("users", r.users); setPulse("top", r.top ? r.top.name : "—");
      draw([...r.recent.map(x => `Кто-то только что купил «${x.name}» × ${x.qty}`), ...base]);
    };
    setTimeout(pulse, 800); setInterval(pulse, 15000);
  }

  // объём: книжка следует за курсором, карточки наклоняются
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const stage = $(".stage"), book = $(".book");
  if (book && !calm) {
    let tx = -28, ty = -10, cx = tx, cy = ty, hover = false;
    stage.addEventListener("pointermove", e => {
      const r = stage.getBoundingClientRect();
      tx = ((e.clientX - r.left) / r.width - .5) * 80; ty = -((e.clientY - r.top) / r.height - .5) * 45; hover = true;
    });
    stage.addEventListener("pointerleave", () => { hover = false; });
    (function loop(t) {
      if (!hover) { tx = -28 + Math.sin(t / 1800) * 24; ty = -10 + Math.cos(t / 2300) * 7; }
      cx += (tx - cx) * .08; cy += (ty - cy) * .08;
      book.style.setProperty("--ry", cx.toFixed(2) + "deg"); book.style.setProperty("--rx", cy.toFixed(2) + "deg");
      requestAnimationFrame(loop);
    })(0);
  }
  if (matchMedia("(hover: hover)").matches && !calm) {
    document.addEventListener("pointermove", e => {
      const c = e.target.closest?.(".card"); if (!c) return;
      const r = c.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
      c.style.setProperty("--ry", ((x - .5) * 12).toFixed(2) + "deg"); c.style.setProperty("--rx", ((.5 - y) * 10).toFixed(2) + "deg");
      c.style.setProperty("--mx", (x * 100).toFixed(1) + "%"); c.style.setProperty("--my", (y * 100).toFixed(1) + "%");
    });
    document.addEventListener("pointerout", e => {
      const c = e.target.closest?.(".card");
      if (c && !c.contains(e.relatedTarget)) { c.style.removeProperty("--rx"); c.style.removeProperty("--ry"); }
    });
  }

  // игры
  const root = $("#games");
  if (!root) return;
  const symbols = JSON.parse(root.dataset.symbols);
  const bal = $("#balance");
  let perClick = 1, pending = 0;

  function apply(s) {
    if (s.balance !== undefined) bal.textContent = fmt(s.balance);
    if (s.per_click) { perClick = s.per_click; $("#per-click").textContent = s.per_click; $("#per-sec").textContent = s.per_sec; }
    if (!s.upgrades) return;
    $("#upgrades").replaceChildren(...s.upgrades.map(u => {
      const row = document.createElement("div"); row.className = "upgrade";
      const info = document.createElement("div");
      const name = document.createElement("div"); name.className = "upgrade__name"; name.textContent = `${u.name} ×${u.owned}`;
      const desc = document.createElement("div"); desc.className = "upgrade__desc"; desc.textContent = u.desc;
      info.append(name, desc);
      const btn = document.createElement("button"); btn.type = "button"; btn.className = "btn btn--sm";
      btn.textContent = u.maxed ? "максимум" : fmt(u.cost); btn.disabled = u.maxed;
      btn.addEventListener("click", async () => { const r = await api("/api/games/upgrade", { key: u.key }); r.ok ? apply(r) : toast(r.error, true); });
      row.append(info, btn); return row;
    }));
  }
  const refresh = async () => { const r = await api("/api/games/state"); if (r.ok) apply(r); };
  refresh(); setInterval(refresh, 15000);

  $("#mine").addEventListener("click", e => {
    pending++;
    const f = document.createElement("span"); f.className = "float-num"; f.textContent = "+" + perClick;
    e.currentTarget.append(f); setTimeout(() => f.remove(), 800);
  });
  setInterval(async () => {
    if (!pending) return;
    const n = pending; pending = 0;
    const r = await api("/api/games/mine", { clicks: n });
    if (r.status === 429 || r.status === 0) pending += n;
    else r.ok ? apply(r) : toast(r.error, true);
  }, 700);

  // автобус
  let bus = null;
  const busBar = $("#bus-bar"), busRes = $("#bus-result"), busStart = $("#bus-start"), busPush = $("#bus-push");
  busStart.addEventListener("click", async () => {
    const r = await api("/api/games/bus/start", {});
    if (!r.ok) { busRes.textContent = r.error; return; }
    bus = { n: 0, goal: r.goal, end: Date.now() + r.seconds * 1000 };
    busBar.style.width = "0"; busRes.textContent = ""; busStart.disabled = true; busPush.disabled = false;
    bus.timer = setInterval(() => Date.now() >= bus.end && finishBus(), 100);
  });
  busPush.addEventListener("click", () => {
    if (!bus) return;
    bus.n++; busBar.style.width = Math.min(100, bus.n / bus.goal * 100) + "%";
    if (bus.n >= bus.goal) finishBus();
  });
  async function finishBus() {
    const n = bus.n; clearInterval(bus.timer); bus = null; busPush.disabled = true;
    const r = await api("/api/games/bus/finish", { pushes: n });
    busRes.textContent = r.message || r.error; if (r.ok) apply(r);
    busStart.disabled = false;
  }

  // казино
  const reels = $$("#reels span"), spin = $("#spin"), out = $("#spin-result");
  spin.addEventListener("click", async () => {
    spin.disabled = true; out.textContent = ""; $("#reels").className = "reels is-spinning";
    const t = setInterval(() => reels.forEach(r => r.textContent = symbols[Math.random() * symbols.length | 0]), 80);
    const [r] = await Promise.all([api("/api/games/spin", { bet: +$("#bet").value }), new Promise(ok => setTimeout(ok, 700))]);
    clearInterval(t);
    $("#reels").className = "reels" + (r.ok && r.payout > +$("#bet").value ? " is-win" : "");
    if (r.ok) { reels.forEach((el, i) => el.textContent = r.reels[i]); apply(r); }
    out.textContent = r.message || r.error;
    setTimeout(() => spin.disabled = false, 500);
  });
})();
