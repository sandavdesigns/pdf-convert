(() => {
  "use strict";

  const storageKey = "msg-to-pdf-theme";
  const validChoices = new Set(["light", "dark", "auto"]);
  const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
  let choice = "auto";

  try {
    const storedChoice = window.localStorage.getItem(storageKey);
    if (validChoices.has(storedChoice)) choice = storedChoice;
  } catch (_) {
    // Storage may be unavailable in hardened browser configurations.
  }

  function effectiveTheme() {
    return choice === "auto" ? (systemTheme.matches ? "dark" : "light") : choice;
  }

  function applyTheme() {
    const effective = effectiveTheme();
    document.documentElement.dataset.theme = effective;
    document.documentElement.dataset.themePreference = choice;
    document.documentElement.style.colorScheme = effective;

    const themeColor = document.getElementById("theme-color");
    if (themeColor) themeColor.content = effective === "dark" ? "#101814" : "#f2f5f3";

    document.querySelectorAll("[data-theme-choice]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.themeChoice === choice));
    });
  }

  function selectTheme(nextChoice) {
    if (!validChoices.has(nextChoice)) return;
    choice = nextChoice;
    try {
      window.localStorage.setItem(storageKey, choice);
    } catch (_) {
      // The selected theme still applies for the current page.
    }
    applyTheme();
  }

  applyTheme();

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-theme-choice]").forEach((button) => {
      button.addEventListener("click", () => selectTheme(button.dataset.themeChoice));
    });
    applyTheme();
  });

  systemTheme.addEventListener?.("change", () => {
    if (choice === "auto") applyTheme();
  });
})();
