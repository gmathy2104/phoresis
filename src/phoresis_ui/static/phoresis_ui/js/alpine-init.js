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
  Alpine.store("palette", {
    open: false,
    query: "",
    items: [],     // populated by topbar with nav_registry.get_flat_items()

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
