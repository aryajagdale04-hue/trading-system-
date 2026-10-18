(function (root, factory) {
  const controls = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = controls;
  if (root && root.document) {
    root.DashboardControls = controls;
    root.addEventListener("DOMContentLoaded", () => {
      controls.initTheme(root.document, root.localStorage);
      controls.initAssistantShortcut(root.document);
    }, { once: true });
  }
})(typeof window !== "undefined" ? window : globalThis, function () {
  const THEME_KEY = "market-explorer-theme";

  function setTheme(document, button, theme, storage) {
    const selected = theme === "light" ? "light" : "dark";
    document.documentElement.dataset.theme = selected;
    if (storage) storage.setItem(THEME_KEY, selected);
    if (button) {
      const nextTheme = selected === "dark" ? "light" : "dark";
      button.textContent = nextTheme === "light" ? "☀ Light" : "☾ Dark";
      button.setAttribute("aria-label", `Switch to ${nextTheme} mode`);
      button.setAttribute("title", `Switch to ${nextTheme} mode`);
    }
    if (document.dispatchEvent && typeof Event !== "undefined") document.dispatchEvent(new Event("dashboard-theme-change"));
    return selected;
  }

  function initTheme(document, storage) {
    const button = document.getElementById("theme-toggle");
    let saved = null;
    try { saved = storage?.getItem(THEME_KEY); } catch (_) { /* storage can be disabled */ }
    setTheme(document, button, saved, null);
    if (button) button.addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      try { setTheme(document, button, next, storage); }
      catch (_) { setTheme(document, button, next, null); }
    });
  }

  function initAssistantShortcut(document) {
    const button = document.getElementById("assistant-shortcut");
    if (!button) return;
    const section = document.getElementById("stock-chat-section");
    const mount = document.getElementById("stock-chat-mount");
    const close = document.getElementById("assistant-chat-close");
    if (!section) return;
    const setOpen = (open) => {
      if (open) section.classList.add("is-open");
      else section.classList.remove("is-open");
      button.setAttribute("aria-expanded", String(open));
      if (open) mount?.querySelector(".chat-input")?.focus({ preventScroll: true });
      else button.focus();
    };
    button.setAttribute("aria-expanded", "false");
    button.addEventListener("click", () => setOpen(!section.classList.contains("is-open")));
    close?.addEventListener("click", () => setOpen(false));
    document.addEventListener?.("keydown", (event) => {
      if (event.key === "Escape" && section.classList.contains("is-open")) setOpen(false);
    });
  }

  return { initTheme, initAssistantShortcut };
});
