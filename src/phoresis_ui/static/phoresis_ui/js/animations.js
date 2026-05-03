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
