const SAVE_KEY = "temnyj-fefu-save";  

//записать прогресс
function saveGame() {
  try {
    localStorage.setItem(SAVE_KEY, JSON.stringify({
      balance: balance,
      owned: upgrades.map(u => u.owned)
    }));
  } catch (e) {
    console.warn("Не удалось сохранить прогресс:", e);
  }
}

function loadGame() {
  try {
    const raw = localStorage.getItem(SAVE_KEY);
    if (raw === null) return;
    const data = JSON.parse(raw);
    if (typeof data.balance === "number") balance = data.balance;
    if (Array.isArray(data.owned)) {
      data.owned.forEach((n, i) => { if (upgrades[i]) upgrades[i].owned = n; });
    }
  } catch (e) {
    console.warn("Не удалось загрузить прогресс:", e);
  }
}

loadGame();
renderUpgrades();
renderCart();

const originalRenderCart = renderCart;
renderCart = function () {
  originalRenderCart();
  saveGame();
};

const originalRenderUpgrades = renderUpgrades;
renderUpgrades = function () {
  originalRenderUpgrades();
  saveGame();
};

//сбросить прогресс
const resetBtn = document.getElementById("reset");
if (resetBtn) {
  resetBtn.addEventListener("click", () => {
    if (confirm("Точно сбросить баланс и улучшения?")) {
      localStorage.removeItem(SAVE_KEY);
      location.reload();
    }
  });
}