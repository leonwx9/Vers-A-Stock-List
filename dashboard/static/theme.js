/* theme.js — light/dark mode switching.

   How it works, start to finish:
   1. This file is loaded in <head>, BEFORE the page is drawn. The first
      block below reads the saved choice from localStorage and stamps
      data-theme="dark" onto <html> immediately — so a dark-mode user never
      sees a white flash while the page loads.
   2. style.css contains two sets of colour variables; the
      html[data-theme="dark"] block wins whenever that stamp is present.
   3. The ☾/☀ button in the header calls toggleTheme() to flip the stamp,
      save the choice, and tell the charts to re-colour themselves. */

(function () {
  if (localStorage.getItem("theme") === "dark") {
    document.documentElement.dataset.theme = "dark";
  }
})();

function isDarkMode() {
  return document.documentElement.dataset.theme === "dark";
}

function toggleTheme() {
  if (isDarkMode()) {
    delete document.documentElement.dataset.theme;   // back to light
    localStorage.setItem("theme", "light");
  } else {
    document.documentElement.dataset.theme = "dark";
    localStorage.setItem("theme", "dark");
  }
  syncThemeExtras();
  // Anything that can't be styled by CSS alone (the charts) listens for
  // this event and re-reads its colours.
  window.dispatchEvent(new Event("themechange"));
}

/* Bits CSS can't reach: the button's icon and the phone status-bar colour. */
function syncThemeExtras() {
  const btn = document.getElementById("theme-btn");
  if (btn) {
    btn.textContent = isDarkMode() ? "☀" : "☾";
    btn.title = isDarkMode() ? "Switch to light mode" : "Switch to dark mode";
  }
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = isDarkMode() ? "#101012" : "#f7f7f7";
}

/* Charts can't use CSS variables directly, so this reads the current values
   for them. Both app.js and ticker.js call it when building a chart. */
function chartThemeColors() {
  const styles = getComputedStyle(document.documentElement);
  return {
    text: styles.getPropertyValue("--chart-text").trim(),
    grid: styles.getPropertyValue("--chart-grid").trim(),
    crosshairLabel: styles.getPropertyValue("--crosshair-label").trim(),
  };
}

/* Wire the button once the page has loaded (the button lives in <body>,
   which doesn't exist yet when this file runs in <head>). */
document.addEventListener("DOMContentLoaded", () => {
  syncThemeExtras();
  const btn = document.getElementById("theme-btn");
  if (btn) btn.addEventListener("click", toggleTheme);
});
