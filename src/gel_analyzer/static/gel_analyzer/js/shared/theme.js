/**
 * Day / night switch of the gel workbench screens (annotation editor, densitometry, comparison).
 *
 * Ported from ds-hub-django (process_development/js/lib/dsh-theme.js), whose names the workbench
 * scripts and stylesheets still use: window.DshTheme, the `dsh:themechange` window event and the
 * `data-dsh-theme-value` buttons. What changed is where the choice lives -- it is Phoresis's own:
 *
 * - localStorage key `phoresis_theme` ("light" | "dark" | "auto"), the key the rest of the
 *   application reads (phoresis_ui/templates/components/base.html), and the profile, saved
 *   best-effort through accounts:theme_set. Choosing Night or Day here changes every page.
 * - On <html>: `data-theme="light"` is Day, no attribute is Night. Stylesheets react to
 *   `:root[data-theme="light"]`. The pre-paint snippet (gel_analyzer/workbench/_theme_head.html)
 *   sets it in <head>; it reads the same key: keep the two in step.
 * - Charts drawn by script cannot follow a stylesheet: they listen to `dsh:themechange`
 *   ({detail: {theme: 'light' | 'dark'}}) and repaint. It also fires when another tab switches.
 */
(function () {
    'use strict';
    if (window.DshTheme) return;

    var KEY = 'phoresis_theme';

    function current() {
        return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
    }

    function resolve(value) {
        if (value === 'light' || value === 'dark') return value;
        return (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
    }

    function syncToggles(theme) {
        var buttons = document.querySelectorAll('[data-dsh-theme-value]');
        for (var i = 0; i < buttons.length; i++) {
            var on = buttons[i].getAttribute('data-dsh-theme-value') === theme;
            buttons[i].setAttribute('aria-pressed', on ? 'true' : 'false');
        }
    }

    function apply(theme) {
        if (theme === 'light') {
            document.documentElement.setAttribute('data-theme', 'light');
        } else {
            document.documentElement.removeAttribute('data-theme');
        }
        syncToggles(theme);
        window.dispatchEvent(new CustomEvent('dsh:themechange', { detail: { theme: theme } }));
    }

    function csrfToken() {
        var match = document.cookie.split('; ').filter(function (c) { return c.indexOf('csrftoken=') === 0; })[0];
        return match ? match.split('=')[1] : '';
    }

    function saveToProfile(theme) {
        var holder = document.querySelector('[data-theme-set-url]');
        var url = holder ? holder.getAttribute('data-theme-set-url') : '';
        var csrf = csrfToken();
        if (!url || !csrf) return;
        fetch(url, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrf, 'Content-Type': 'application/x-www-form-urlencoded' },
            body: 'theme=' + encodeURIComponent(theme),
            credentials: 'same-origin',
        }).catch(function () { /* the browser's copy is enough for this device */ });
    }

    function set(theme) {
        theme = theme === 'light' ? 'light' : 'dark';
        try {
            localStorage.setItem(KEY, theme);
        } catch (e) {
            // Storage blocked (private window, policy): the switch still works
            // for this page, it just is not remembered by this browser.
        }
        saveToProfile(theme);
        if (theme !== current()) apply(theme);
    }

    document.addEventListener('click', function (e) {
        var btn = e.target && e.target.closest ? e.target.closest('[data-dsh-theme-value]') : null;
        if (!btn) return;
        e.preventDefault();
        set(btn.getAttribute('data-dsh-theme-value'));
    });

    window.addEventListener('storage', function (e) {
        if (e.key !== KEY) return;
        var theme = resolve(e.newValue);
        if (theme !== current()) apply(theme);
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { syncToggles(current()); });
    } else {
        syncToggles(current());
    }

    window.DshTheme = { KEY: KEY, get: current, set: set };
})();
