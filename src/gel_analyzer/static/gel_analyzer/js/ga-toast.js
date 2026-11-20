/* window.gaToast(message, type): a short notice in the top-right corner, gone after 4 s.
 *
 * The gel pages' one notice helper, loaded by both gel bases (_ga_modern_base.html and _ga_base_minimal.html), which
 * each carried an inline copy until 2026-10-31 (spec docs/superpowers/specs/2026-10-31-gel-modern-pages-design.md,
 * section 4). type: success | warning (the default) | danger | info. The message is set as text, never as HTML.
 */
(function () {
    'use strict';

    var COLORS = { success: '#198754', warning: '#ffc107', danger: '#dc3545', info: '#0d6efd' };
    var ICONS = { success: 'check-circle', warning: 'exclamation-triangle', danger: 'x-circle', info: 'info-circle' };

    var style = document.createElement('style');
    style.textContent = '@keyframes gaToastIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }';
    document.head.appendChild(style);

    window.gaToast = function (message, type) {
        type = COLORS[type] ? type : 'warning';
        var toast = document.createElement('div');
        // Dark text on the amber warning: white on #ffc107 read at ~1.6:1.
        var ink = type === 'warning' ? '#1f2937' : '#fff';
        toast.style.cssText = 'position:fixed;top:20px;right:20px;z-index:99999;min-width:300px;max-width:500px;'
            + 'padding:16px 20px;border-radius:8px;font-size:0.9rem;box-shadow:0 4px 12px rgba(0,0,0,0.15);'
            + 'display:flex;align-items:center;gap:10px;animation:gaToastIn 0.3s ease;'
            + 'color:' + ink + ';background:' + COLORS[type];
        toast.setAttribute('role', type === 'danger' ? 'alert' : 'status');
        var icon = document.createElement('i');
        icon.className = 'bi bi-' + ICONS[type];
        icon.style.cssText = 'font-size:1.2rem;flex-shrink:0';
        icon.setAttribute('aria-hidden', 'true');
        var text = document.createElement('span');
        text.textContent = message;
        toast.appendChild(icon);
        toast.appendChild(text);
        document.body.appendChild(toast);
        setTimeout(function () {
            toast.style.opacity = '0';
            toast.style.transition = 'opacity 0.3s';
            setTimeout(function () { toast.remove(); }, 300);
        }, 4000);
    };
}());
