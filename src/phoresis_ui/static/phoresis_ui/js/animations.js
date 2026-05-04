/* Animation helpers — view-transition wrapper + CountUp.js init for KPIs. */
(function () {
  // CountUp.js — load lazily on demand
  let CountUpModule = null;

  async function ensureCountUp() {
    if (CountUpModule) return CountUpModule;
    const m = await import("https://unpkg.com/countup.js@2.8.0/dist/countUp.min.js");
    CountUpModule = m.CountUp || window.CountUp;
    return CountUpModule;
  }

  async function initCountUps(root = document) {
    const targets = root.querySelectorAll("[data-countup]");
    if (!targets.length) return;
    const Up = await ensureCountUp();
    targets.forEach((el) => {
      const value = parseFloat(el.dataset.countup);
      const duration = parseInt(el.dataset.countupDuration || "800", 10) / 1000;
      if (!Number.isFinite(value)) return;
      const u = new Up(el, value, { duration, useEasing: true });
      if (!u.error) u.start();
      el.removeAttribute("data-countup");
    });
  }

  // Run on initial load + whenever HTMX swaps content
  document.addEventListener("DOMContentLoaded", () => initCountUps());
  document.addEventListener("htmx:afterSwap", (e) => initCountUps(e.detail.elt));

  // View-transition wrapper for HTMX page swaps (Chrome / Edge)
  if (typeof document.startViewTransition === "function") {
    document.addEventListener("htmx:beforeSwap", (e) => {
      if (e.detail.swapStyle === "outerHTML" || e.target === document.body) {
        document.startViewTransition(() => {
          // HTMX completes the swap synchronously inside this callback
        });
      }
    });
  }
})();

// ============================================================================
// Ripple effect on buttons (opt-in via data-ripple on the host element)
// ============================================================================
document.addEventListener("click", (e) => {
  const host = e.target.closest("[data-ripple]");
  if (!host) return;
  host.classList.add("ui-ripple-host");
  const rect = host.getBoundingClientRect();
  const size = Math.max(rect.width, rect.height);
  const ripple = document.createElement("span");
  ripple.className = "ui-ripple";
  ripple.style.width = ripple.style.height = `${size}px`;
  ripple.style.left = `${e.clientX - rect.left - size / 2}px`;
  ripple.style.top  = `${e.clientY - rect.top  - size / 2}px`;
  host.appendChild(ripple);
  setTimeout(() => ripple.remove(), 600);
});

// ============================================================================
// HTMX top progress bar
// ============================================================================
(function () {
  let bar = null;

  function ensureBar() {
    if (bar) return bar;
    bar = document.createElement("div");
    bar.className = "ui-htmx-progress";
    document.body.appendChild(bar);
    return bar;
  }

  document.addEventListener("htmx:beforeRequest", () => ensureBar().setAttribute("data-state", "loading"));
  document.addEventListener("htmx:afterRequest",  () => ensureBar().setAttribute("data-state", "done"));
  document.addEventListener("htmx:responseError", () => ensureBar().setAttribute("data-state", "done"));
})();
