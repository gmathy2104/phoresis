/* Alpine.js 3 stores — theme, toast, modal, palette. */

// localStorage helpers that are safe under Edge "Tracking Prevention" /
// Safari "Lockdown Mode" / Firefox "Strict" / private windows. Some of those
// modes throw SecurityError on read or write; if any localStorage access
// throws inside `alpine:init`, the whole listener aborts and EVERY store
// fails to register, cascading into "$store.theme is undefined" everywhere.
function safeLocalGet(key, fallback) {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}
function safeLocalSet(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* silently drop -- the in-memory `user` field is still authoritative */
  }
}

document.addEventListener("alpine:init", () => {
  // ---- theme ----
  Alpine.store("theme", {
    user: safeLocalGet("phoresis_theme", "auto"),  // 'auto' | 'light' | 'dark'

    init() {
      this.apply();
      // Re-apply when system pref flips while on 'auto'
      matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
        if (this.user === "auto") this.apply();
      });
    },

    set(value) {
      this.user = value;
      safeLocalSet("phoresis_theme", value);
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
  // Static `pages` come from window.PHORESIS_PALETTE_ITEMS (server-rendered
  // by the topbar from nav_registry). Entity matches (analyses, comparisons,
  // gel images) are fetched on-the-fly from /api/search/ as the user types.
  Alpine.store("palette", {
    open: false,
    query: "",
    pages: (window.PHORESIS_PALETTE_ITEMS || []).map((p) => ({
      type: "page",
      type_label: p.type === "action" ? "Action" : "Page",
      name: p.name,
      url: p.url,
      icon: p.icon,
    })),
    entities: [],
    activeIndex: 0,
    loading: false,
    _abort: null,
    _debounce: null,

    show()  { this.open = true; this.activeIndex = 0; },
    hide()  {
      this.open = false;
      this.query = "";
      this.entities = [];
      this.activeIndex = 0;
      if (this._abort) { this._abort.abort(); this._abort = null; }
    },
    toggle() { this.open ? this.hide() : this.show(); },

    /** Filter the static page list against the current query. */
    get filteredPages() {
      const q = this.query.trim().toLowerCase();
      if (!q) return this.pages.slice(0, 8);
      return this.pages.filter((p) => p.name.toLowerCase().includes(q));
    },

    /** Combined visible result list (pages first, then entities). */
    get results() {
      return [...this.filteredPages, ...this.entities];
    },

    /** Trigger an /api/search/ fetch (debounced). Bound to query via x-effect. */
    onQueryChanged() {
      const q = this.query.trim();
      this.activeIndex = 0;
      if (this._debounce) clearTimeout(this._debounce);
      if (!q) {
        this.entities = [];
        this.loading = false;
        if (this._abort) { this._abort.abort(); this._abort = null; }
        return;
      }
      this._debounce = setTimeout(() => this._fetch(q), 180);
    },

    async _fetch(q) {
      if (this._abort) this._abort.abort();
      this._abort = new AbortController();
      this.loading = true;
      try {
        const resp = await fetch(`/api/search/?q=${encodeURIComponent(q)}`, {
          signal: this._abort.signal,
          headers: { Accept: "application/json" },
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (data.query === this.query.trim()) {
          this.entities = data.results || [];
        }
      } catch (err) {
        if (err.name !== "AbortError") {
          console.error("Search failed:", err);
          this.entities = [];
        }
      } finally {
        this.loading = false;
      }
    },

    move(delta) {
      const max = this.results.length - 1;
      if (max < 0) return;
      this.activeIndex = Math.max(0, Math.min(max, this.activeIndex + delta));
      // Keep the highlighted item visible inside the scrollable result list
      requestAnimationFrame(() => {
        const list = document.querySelector('[data-palette-list]');
        const active = list?.querySelector('[data-palette-active="true"]');
        if (active && typeof active.scrollIntoView === "function") {
          active.scrollIntoView({ block: "nearest" });
        }
      });
    },

    activate() {
      const item = this.results[this.activeIndex];
      if (item && item.url) {
        this.hide();
        window.location.href = item.url;
      }
    },
  });
});

// Inline theme application happens in base.html before alpine:init -- guard
// the same operation here too so that even if the inline script's localStorage
// access was blocked, alpine:init does not throw.

// Ctrl+K / Cmd+K opens the palette
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "k") {
    e.preventDefault();
    if (window.Alpine?.store("palette")) Alpine.store("palette").toggle();
  }
});
