/* Alpine.js 3 stores — theme, toast, modal, palette. */
document.addEventListener("alpine:init", () => {
  // ---- theme ----
  Alpine.store("theme", {
    user: localStorage.getItem("phoresis_theme") || "auto",  // 'auto' | 'light' | 'dark'

    init() {
      this.apply();
      // Re-apply when system pref flips while on 'auto'
      matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
        if (this.user === "auto") this.apply();
      });
    },

    set(value) {
      this.user = value;
      localStorage.setItem("phoresis_theme", value);
      this.apply();

      // Persist to server (best-effort; localStorage is the canonical client store)
      const csrf = document.querySelector("[name=csrfmiddlewaretoken]")?.value
        || document.cookie.split("; ").find(c => c.startsWith("csrftoken="))?.split("=")[1];
      if (csrf && document.body.dataset.user !== "anonymous") {
        fetch(window.PHORESIS_URLS.theme_set, {
          method: "POST",
          headers: { "X-CSRFToken": csrf, "Content-Type": "application/x-www-form-urlencoded" },
          body: `theme=${encodeURIComponent(value)}`,
          credentials: "same-origin",
        }).catch(() => { /* silent — localStorage is the source of truth */ });
      }
    },

    apply() {
      const resolved = this.user === "auto"
        ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
        : this.user;
      document.documentElement.setAttribute("data-theme", resolved);
      document.documentElement.dataset.userTheme = this.user;
      // Notify chart code to re-render with the new palette
      window.dispatchEvent(new CustomEvent("phoresis:theme-changed", { detail: { theme: resolved } }));
    },
  });

  // ---- toast ----
  Alpine.store("toast", {
    items: [],
    counter: 0,

    push({ variant = "info", title, message = "", duration = 5000 }) {
      const id = ++this.counter;
      this.items.push({ id, variant, title, message });
      if (duration > 0) setTimeout(() => this.dismiss(id), duration);
    },

    dismiss(id) {
      this.items = this.items.filter((t) => t.id !== id);
    },
  });

  // ---- modal ----
  Alpine.store("modal", {
    open: null,  // ID of the currently-open modal, or null

    show(id) { this.open = id; },
    close()  { this.open = null; },
    toggle(id) { this.open = this.open === id ? null : id; },
  });

  // ---- command palette ----
  // `items` is sourced from window.PHORESIS_PALETTE_ITEMS, which the topbar
  // template populates inline at render time (so navigation registry data
  // can be Django-rendered, then handed off to Alpine here without any
  // alpine:init listener-ordering footguns).
  Alpine.store("palette", {
    open: false,
    query: "",
    items: window.PHORESIS_PALETTE_ITEMS || [],

    show()  { this.open = true; },
    hide()  { this.open = false; this.query = ""; },
    toggle() { this.open ? this.hide() : this.show(); },
  });
});

// Ctrl+K / Cmd+K opens the palette
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "k") {
    e.preventDefault();
    if (window.Alpine?.store("palette")) Alpine.store("palette").toggle();
  }
});
