const UNI = "двфу";

const products = [
  { id: 2, stars: 3, icon: "🔑", name: "Пароль 123456 (надёжный)",
    price: 5, review: "Взломали за 0,3 секунды, но уважение осталось." },
  { id: 3, stars: 4, icon: "🧦", name: "Один (1) носок",
    price: 15, review: "Второй пришёл отдельной посылкой через месяц." },
  { id: 4, stars: 3, icon: "🤖", name: "Кнопка «Я не робот» (я робот)",
    price: 60, review: "Нажала, и меня попросили найти светофоры. Нашла не все." },
  { id: 6, stars: 1, icon: "📜", name: "Инструкция «Как не откладывать на потом»",
    price: 25, review: "Прочитаю завтра. Звёзд поставлю тоже завтра." },

  { id: 7, stars: 2, icon: "📈", name: "Автомат по матанализу (б/у)",
    price: 300, review: "Купила, открыла зачётку, а там интеграл. Курьер просил не трогать." },
  { id: 9, stars: 5, icon: "📶", name: "Сигнал Wi-Fi (одна палочка, только у окна на третьем этаже)",
    price: 55, review: "Стояла у окна 40 минут, загрузилась половина страницы. Лучший день сессии." },
  { id: 12, stars: 1, icon: "🚪", name: "Курочкина И.А. больше вас не беспокоит",
    price: 500, review: "Дорого, не хватило даже на пол пары. Не рекомендую." },
  { id: 13, stars: 4, icon: "🚿", name: "Горячая вода в общаге (на 30 секунд)",
    price: 250, review: "Включила, обрадовалась, и снова полилась холодная." },
  { id: 14, stars: 3, icon: "🚌", name: "Место в автобусе от кампуса (стоячее, зато моё)",
    price: 90, review: "Ехала на подножке, с прикольным видом. Курьер не влез, доставили на следующей остановке." },
  { id: 15, stars: 5, icon: "🍛", name: "Казан плова (взрывоопасный)",
    price: 120, review: "Пришёл целым. Кухня не пережила. Плов, говорят, вышел отличный." },
  { id: 16, stars: 5, icon: "🪵", name: "Щепки от кухни в общаге (на память)",
    price: 35, review: "Привезли в пакете. Пахнет пловом. Повесила на стену как картину." },
  { id: 17, stars: 1, icon: "🏅", name: "Рейтинг 5.0 (для заселения в общагу)",
    price: 999, review: "Купила, показала в деканате. Развернули и послали подальше..." },
  { id: 18, stars: 1, icon: "🏚️", name: "Квартира, самая ужасная (от 30 000)",
    price: 30000, review: "Не купил. Не потяну. Живу под мостом в палатке, зато дешевле." },
  { id: 19, stars: 4, icon: "🗺️", name: "Карта корпуса E (нижние этажи, выход не указан)",
    price: 80, review: "Зашел на лекцию, вышел через три дня. Курьер до сих пор там." }
];

let balance = 400;
let cart = [];            
let busy = false;         

const catalogEl = document.getElementById("catalog");
const cartEl = document.getElementById("cart");
const totalEl = document.getElementById("total");
const balanceEl = document.getElementById("balance");
const statusEl = document.getElementById("status");
const trackEl = document.getElementById("track");
const searchEl = document.getElementById("search");


const glitches = [
  "Подключение через 14 прокси… ошибка: нет денег на балансе.",
  "Курьер найден. Курьер потерян.",
  "Wi-Fi в корпусе не обнаружен. Но вы это и так знали.",
  "Горячая вода: не найдена. Холодная: в наличии.",
  "Курьер найден на нижних этажах корпуса E.",
  "Автобус от кампуса заполнен. Следующий тоже.",
  "Корпус E: вы находитесь здесь. Выход не найден.",
  "Курс зачётки упал: 1 зачётка = 3 бессонные ночи.",
];
setInterval(() => {
  statusEl.textContent = glitches[Math.floor(Math.random() * glitches.length)];
}, 5000);


function renderCatalog() {
  const query = searchEl.value.toLowerCase();
  const list = products.filter(p =>
    p.name.toLowerCase().includes(query)
  );
  catalogEl.innerHTML = list.map(p => `
    <article class="card">
      <div class="icon">${p.icon}</div>
      <h3>${p.name}</h3>
      <span class="price">${p.price} зачёток</span>
      <button class="add" onclick="addToCart(${p.id})">В корзину</button>
      <div class="review">
        <div class="stars" aria-label="Оценка: ${p.stars} из 5">${"★".repeat(p.stars)}${"☆".repeat(5 - p.stars)}</div>
        «${p.review}»
      </div>
    </article>
  `).join("") || "<p>Ничего не найдено. Даже в даркнете.</p>";
}

function renderCart() {
  cartEl.innerHTML = cart.length
    ? cart.map((id, i) => {
        const p = products.find(x => x.id === id);
        return `<div class="cart-row"><span>${p.icon} ${p.name}</span>
                <button onclick="removeFromCart(${i})">✕</button></div>`;
      }).join("")
    : "<p class='tag'>Пусто. Как кошелёк в конце месяца.</p>";
  totalEl.textContent = getTotal();
  balanceEl.textContent = balance;
}

function getTotal() {
  return cart.reduce((sum, id) => sum + products.find(p => p.id === id).price, 0);
}
function addToCart(id) { if (!busy) { cart.push(id); renderCart(); } }
function removeFromCart(i) { if (!busy) { cart.splice(i, 1); renderCart(); } }

document.getElementById("checkout").addEventListener("click", () => {
  if (busy || cart.length === 0) return;
  const total = getTotal();
  if (total > balance) {
    statusEl.textContent = "Ошибка 402: не хватает зачёток. Попробуйте сдать что-нибудь вовремя.";
    document.querySelector("aside").classList.add("shake");
    setTimeout(() => document.querySelector("aside").classList.remove("shake"), 400);
    return;
  }
  balance -= total;
  cart = [];
  renderCart();
  startDelivery();
});


function startDelivery() {
  busy = true;
  const steps = [
    "Курьер вышел из деканата",
    "Курьер заблудился на третьем этаже",
    "Курьер ждёт у закрытой аудитории",
    "Курьер пошёл пересдавать вашу доставку",
    "Доставлено (или нет)"
  ];
  trackEl.innerHTML = steps.map(s => `<li>○ ${s}</li>`).join("");
  const items = trackEl.querySelectorAll("li");
  items.forEach((li, i) => {
    setTimeout(() => {
      li.classList.add("done");
      li.textContent = "● " + steps[i];
      if (i === steps.length - 1) busy = false;
    }, (i + 1) * 2400);
  });
}

searchEl.addEventListener("input", renderCatalog);

renderCatalog();
renderCart();