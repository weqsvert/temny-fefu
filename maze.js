//карта корпуса
const MAZE = [
  "###########",
  "#S..#.....#",
  "#.#.#.###.#",
  "#.#...#...#",
  "#.#####.###",
  "#.....#...#",
  "###.#.###.#",
  "#...#.....#",
  "#########E#"
];
const CELL = 24;                 
const WANDER_STEPS = 130;   
const STEP_MS = 200;           

const ROWS = MAZE.length;
const COLS = MAZE[0].length;

const mazeWrap = document.createElement("div");
mazeWrap.className = "maze";
mazeWrap.hidden = true;
mazeWrap.innerHTML = `
  <canvas id="mazeCanvas" width="${COLS * CELL}" height="${ROWS * CELL}"
          aria-label="Карта корпуса E с курьером"></canvas>
  <p class="hint" id="mazeText"></p>
`;
trackEl.insertAdjacentElement("afterend", mazeWrap);

const canvas = document.getElementById("mazeCanvas");
const ctx = canvas.getContext("2d");
const mazeText = document.getElementById("mazeText");

const css = getComputedStyle(document.documentElement);
const color = name => css.getPropertyValue(name).trim();

function findCell(ch) {
  for (let r = 0; r < ROWS; r++) {
    const c = MAZE[r].indexOf(ch);
    if (c !== -1) return { r, c };
  }
}
const START = findCell("S");
const EXIT = findCell("E");

function neighbors(cell) {
  const { r, c } = cell;
  return [[r - 1, c], [r + 1, c], [r, c - 1], [r, c + 1]]
    .filter(([y, x]) => MAZE[y] && MAZE[y][x] && MAZE[y][x] !== "#")
    .map(([y, x]) => ({ r: y, c: x }));
}
const same = (a, b) => a && b && a.r === b.r && a.c === b.c;
const key = cell => cell.r + "," + cell.c;

function shortestPath(from) {
  const queue = [from];
  const cameFrom = new Map([[key(from), null]]);
  while (queue.length) {
    const cur = queue.shift();
    if (same(cur, EXIT)) break;
    for (const n of neighbors(cur)) {
      if (!cameFrom.has(key(n))) {
        cameFrom.set(key(n), cur);
        queue.push(n);
      }
    }
  }
  const path = [];
  let cur = EXIT;
  while (cur && !same(cur, from)) {
    path.unshift(cur);
    cur = cameFrom.get(key(cur));
  }
  return path;
}

function buildRoute() {
  const route = [];
  let pos = START;
  let prev = null;
  for (let i = 0; i < WANDER_STEPS; i++) {
    let options = neighbors(pos).filter(n => !same(n, EXIT));  
    const forward = options.filter(n => !same(n, prev));        
    const pool = forward.length ? forward : options;
    const next = pool[Math.floor(Math.random() * pool.length)];
    route.push(next);
    prev = pos;
    pos = next;
  }
  return route.concat(shortestPath(pos));
}

//отрисовка лабиринта
let courier = START;
let trail = new Set();

function drawMaze() {
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      const x = c * CELL, y = r * CELL;
      const wall = MAZE[r][c] === "#";
      ctx.fillStyle = wall ? color("--line") : color("--bg");
      ctx.fillRect(x, y, CELL, CELL);
      if (!wall && trail.has(r + "," + c)) {      // след, где курьер уже был
        ctx.globalAlpha = 0.2;
        ctx.fillStyle = color("--accent");
        ctx.fillRect(x, y, CELL, CELL);
        ctx.globalAlpha = 1;
      }
    }
  }
  ctx.font = (CELL - 6) + "px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("🏁", EXIT.c * CELL + CELL / 2, EXIT.r * CELL + CELL / 2);
  ctx.fillText("🛵", courier.c * CELL + CELL / 2, courier.r * CELL + CELL / 2);
}

//запуск

const DELIVERY_STEPS = [
  "Курьер вышел из деканата",
  "Курьер заблудился на третьем этаже",
  "Курьер ждёт у закрытой аудитории",
  "Курьер пошёл пересдавать вашу доставку",
  "Доставлено (или нет)"
];
// На какой доле пути загорается каждый шаг (0 = старт, 1 = выход)
const STEP_AT = [0, 0.25, 0.5, 0.75, 1];

let mazeTimer = null;

function runMaze() {
  clearInterval(mazeTimer);              
  const route = buildRoute();
  let i = 0;                              
  let lit = 0;                            

  busy = true;                            // пока идёт доставка корзину не трогаем
  trackEl.innerHTML = DELIVERY_STEPS.map(s => `<li>○ ${s}</li>`).join("");
  const items = trackEl.querySelectorAll("li");

  function lightSteps() {
    while (lit < DELIVERY_STEPS.length && i >= Math.round(route.length * STEP_AT[lit])) {
      items[lit].classList.add("done");
      items[lit].textContent = "● " + DELIVERY_STEPS[lit];
      lit++;
    }
  }

  courier = START;
  trail = new Set([key(START)]);
  mazeWrap.hidden = false;
  mazeText.textContent = "Курьер зашёл в корпус E. Нижние этажи. Связи нет.";
  drawMaze();
  lightSteps();                          

  mazeTimer = setInterval(() => {
    if (i >= route.length) {
      clearInterval(mazeTimer);
      busy = false;
      mazeText.textContent = "Курьер выбрался из корпуса E. Посылка доставлена (почти).";
      return;
    }
    courier = route[i++];
    trail.add(key(courier));
    if (i === WANDER_STEPS) mazeText.textContent = "Курьер заблудился, но нашёл знак «Выход».";
    lightSteps();
    drawMaze();
  }, STEP_MS);
}

startDelivery = runMaze;

const originalStartDelivery = startDelivery;
startDelivery = function () {
  originalStartDelivery();
  runMaze();
};