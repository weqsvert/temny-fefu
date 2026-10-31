function earn(n) {
  balance += n;
  renderCart();
}

const gamesSection = document.createElement("section");
gamesSection.className = "games";
gamesSection.innerHTML = `
  <h2>Подработка и риск</h2>
  <div class="games-grid">

    <div class="game">
      <h3>Майнинг зачёток</h3>
      <button id="mine" aria-label="Майнить зачётку">🎓</button>
      <p class="hint">+<span id="perClick">1</span> за клик, +<span id="perSec">0</span> в секунду</p>
      <div id="upgrades"></div>
    </div>

    <div class="game">
      <h3>Успей на автобус</h3>
      <p class="hint" id="busText">Автобус уже подъезжает. Нужно протиснуться 15 раз за 5 секунд.</p>
      <div class="bar"><div id="busBar"></div></div>
      <button class="act" id="busBtn">Встать в очередь</button>
    </div>

    <div class="game">
      <h3>Казино «Последний автомат»</h3>
      <div class="reels"><span id="r0">🎓</span><span id="r1">📈</span><span id="r2">🚌</span></div>
      <label class="hint">Ставка:
        <select id="bet">
          <option value="10">10 зачёток</option>
          <option value="20" selected>20 зачёток</option>
          <option value="50">50 зачёток</option>
        </select>
      </label>
      <button class="act" id="spin">Крутить</button>
      <p class="hint" id="casinoText">Три одинаковых: ставка ×10. Два: ставка возвращается.</p>
    </div>

  </div>
`;
document.querySelector("main").appendChild(gamesSection);


//кликер
const upgrades = [
  { name: "Энергетик",     base: 50,  clickBonus: 1, secBonus: 0, owned: 0 },
  { name: "Шпаргалка",     base: 100, clickBonus: 0, secBonus: 1, owned: 0 },
  { name: "Староста",      base: 400, clickBonus: 0, secBonus: 5, owned: 0 }
];
let perClick = 1;
let perSec = 0;

const upgradeCost = u => Math.round(u.base * Math.pow(1.5, u.owned));

function renderUpgrades() {
  perClick = 1 + upgrades.reduce((s, u) => s + u.owned * u.clickBonus, 0);
  perSec = upgrades.reduce((s, u) => s + u.owned * u.secBonus, 0);
  document.getElementById("perClick").textContent = perClick;
  document.getElementById("perSec").textContent = perSec;
  document.getElementById("upgrades").innerHTML = upgrades.map((u, i) =>
    `<button class="act" onclick="buyUpgrade(${i})">${u.name} ×${u.owned} за ${upgradeCost(u)}</button>`
  ).join("");
}

function buyUpgrade(i) {
  const cost = upgradeCost(upgrades[i]);
  if (balance < cost) {
    statusEl.textContent = "Не хватает зачёток на улучшение. Покликай ещё.";
    return;
  }
  earn(-cost);
  upgrades[i].owned++;
  renderUpgrades();
}

document.getElementById("mine").addEventListener("click", () => earn(perClick));
setInterval(() => { if (perSec > 0) earn(perSec); }, 1000);  // пассивный доход
renderUpgrades();

//автобус

const BUS_GOAL = 15;      
const BUS_TIME = 5000;    
const BUS_REWARD = 40;    
const busBtn = document.getElementById("busBtn");
const busBar = document.getElementById("busBar");
const busText = document.getElementById("busText");
let busPushes = 0;
let busTimer = null;
let busEnd = 0;

const busFails = [
  "Автобус уехал. Ты остался(-ась) на остановке с ещё 200 людьми.",
  "Двери закрылись прямо перед носом. Классика.",
  "Автобус был забит, водитель только вздохнул и уехал."
];

busBtn.addEventListener("click", () => {
  if (busTimer === null) {          
    busPushes = 0;
    busEnd = Date.now() + BUS_TIME;
    busTimer = setInterval(busTick, 100);
    busBtn.textContent = "Протискиваться!";
  }
  busPushes++;
  busBar.style.width = Math.min(100, busPushes / BUS_GOAL * 100) + "%";
  if (busPushes >= BUS_GOAL) busFinish(true);
});

function busTick() {
  const left = busEnd - Date.now();
  if (left <= 0) { busFinish(false); return; }
  busText.textContent = `Двери закрываются через ${(left / 1000).toFixed(1)} с`;
}

function busFinish(win) {
  clearInterval(busTimer);
  busTimer = null;
  busBtn.textContent = "Встать в очередь";
  if (win) {
    earn(BUS_REWARD);
    busText.textContent = `Влез(-ла)! Стоишь на одной ноге, зато едешь. +${BUS_REWARD} зачёток.`;
  } else {
    busText.textContent = busFails[Math.floor(Math.random() * busFails.length)];
  }
  setTimeout(() => { busBar.style.width = "0%"; }, 600);
}


//казик

const symbols = ["🎓", "📈", "🚌", "🍛", "💀"];
const reels = [0, 1, 2].map(i => document.getElementById("r" + i));
const spinBtn = document.getElementById("spin");
const casinoText = document.getElementById("casinoText");
let spinning = false;

const randomSymbol = () => symbols[Math.floor(Math.random() * symbols.length)];

spinBtn.addEventListener("click", () => {
  if (spinning) return;
  const bet = Number(document.getElementById("bet").value);
  if (balance < bet) {
    casinoText.textContent = "Недостаточно зачёток. Казино в долг не играет.";
    return;
  }
  earn(-bet);
  spinning = true;
  casinoText.textContent = "Крутится…";

  const anim = setInterval(() => reels.forEach(r => r.textContent = randomSymbol()), 80);

  setTimeout(() => {
    clearInterval(anim);
    const result = reels.map(() => randomSymbol());
    reels.forEach((r, i) => r.textContent = result[i]);
    showCasinoResult(result, bet);
    spinning = false;
  }, 1000);
});

function showCasinoResult(result, bet) {
  const [a, b, c] = result;
  if (a === b && b === c) {
    if (a === "💀") {
      casinoText.textContent = "Три черепа. Ну лян, с кем не бывает...";
    } else {
      earn(bet * 10);
      casinoText.textContent = `ДЖЕКПОТ! Три ${a}. Выигрыш: ${bet * 10} зачёток.`;
    }
  } else if (a === b || b === c || a === c) {
    earn(bet);
    casinoText.textContent = "Два одинаковых. Ставка возвращается, но осадочек остался.";
  } else {
    casinoText.textContent = "Мимо. Казино благодарит за вклад в стипендиальный фонд.";
  }
}