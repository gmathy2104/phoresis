/* HTMX 2 wiring — CSRF, indicators, auto-toast on response status. */
(function () {
  if (typeof window.htmx === "undefined") {
    document.addEventListener("htmx:load", configure, { once: true });
  } else {
    configure();
  }

  function configure() {
    // CSRF — Django needs the token on every unsafe request
    htmx.on("htmx:configRequest", (e) => {
      const token = document.querySelector("[name=csrfmiddlewaretoken]")?.value
        || readCookie("csrftoken");
      if (token) {
        e.detail.headers["X-CSRFToken"] = token;
      }
    });

    // Auto-toast on 4xx/5xx
    htmx.on("htmx:responseError", (e) => {
      if (window.Alpine && Alpine.store("toast")) {
        Alpine.store("toast").push({
          variant: "danger",
          title: `Request failed (${e.detail.xhr.status})`,
          message: e.detail.xhr.statusText,
        });
      }
    });

    // Auto-toast on the X-Toast-* response headers (server can push toasts)
    htmx.on("htmx:afterRequest", (e) => {
      const xhr = e.detail.xhr;
      const variant = xhr.getResponseHeader("X-Toast-Variant");
      const title = xhr.getResponseHeader("X-Toast-Title");
      const message = xhr.getResponseHeader("X-Toast-Message");
      if (title && window.Alpine?.store("toast")) {
        Alpine.store("toast").push({ variant: variant || "info", title, message });
      }
    });
  }

  function readCookie(name) {
    return document.cookie
      .split("; ")
      .find((c) => c.startsWith(name + "="))
      ?.split("=")[1];
  }
})();
