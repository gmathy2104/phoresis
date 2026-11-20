/**
 * GelAnalyzer.Workbench.Summary — the summary strip of the gel workbench pages.
 *
 * Renders services/analysis_detail.py::summary_payload: the analysis page's metric cards, then its checks (worst
 * first), then the status hint (spec docs/superpowers/specs/2026-10-12-gel-modern-ui-design.md §3). It prints the
 * payload and computes nothing: the server decides every value, label, check and link.
 *
 * Each check is a button: a click or Enter opens its detail and its link under the strip (no hover-only text, so a
 * touch screen and a keyboard reach it). The host re-renders after a run, a reference change or a quantification
 * save, with the payload of the densitometry API (`page_summary`).
 *
 * Foundation rule (gel_analyzer/CLAUDE.md): `x = x || {}` namespaces, nothing at load time.
 */
(function (global) {
    'use strict';

    const GA = (global.GelAnalyzer = global.GelAnalyzer || {});
    const WB = (GA.Workbench = GA.Workbench || {});

    function esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    // Units keep their case under an uppercased label (docs/handover/known-traps.md): µg/mL, kDa.
    function unitText(value) {
        return esc(value).replace(
            /([µμ][A-Za-z]*(?:\/[A-Za-z]+)?|\bkDa\b)/g,
            '<span class="ga-wb-unit-text">$1</span>'
        );
    }

    function cardHtml(card) {
        const classes = ['ga-wb-card'];
        if (card.readout) classes.push('ga-wb-card--readout');
        if (card.tone) classes.push(`ga-wb-card--${card.tone}`);
        const icon = card.readout ? '<i class="bi bi-eyedropper" aria-hidden="true"></i>' : '';
        return `<div class="${classes.join(' ')}"${card.title ? ` title="${esc(card.title)}"` : ''}>
            <div class="ga-wb-card-label">${icon}${unitText(card.label)}</div>
            <div class="ga-wb-card-value">${unitText(card.value)}</div>
            ${card.sub ? `<div class="ga-wb-card-sub" title="${esc(card.sub)}">${unitText(card.sub)}</div>` : ''}
        </div>`;
    }

    function checkIcon(level) {
        return level === 'warn' ? 'bi-exclamation-triangle-fill' : 'bi-info-circle-fill';
    }

    function render(root, payload) {
        if (!root) return;
        if (!payload) {
            root.innerHTML = '';
            root.hidden = true;
            return;
        }
        root.hidden = false;
        const checks = payload.checks || [];
        const detailId = `${root.id || 'ga-wb-summary'}-detail`;
        const title = checks.length
            ? `<span class="ga-wb-checks-title"><i class="bi bi-list-check" aria-hidden="true"></i>To check · ${checks.length}</span>`
            : '<span class="ga-wb-checks-title ga-wb-checks-title--ok"><i class="bi bi-check2-circle" aria-hidden="true"></i>Nothing missing</span>';
        const buttons = checks
            .map(
                (check, index) => `<button type="button" class="ga-wb-check ga-wb-check--${esc(check.level)}"
                    data-check="${index}" aria-expanded="false" aria-controls="${esc(detailId)}">
                    <i class="bi ${checkIcon(check.level)}" aria-hidden="true"></i>${unitText(check.title)}</button>`
            )
            .join('');
        const hint = payload.hint
            ? `<span class="ga-wb-hint${payload.hint.tone ? ` ga-wb-hint--${esc(payload.hint.tone)}` : ''}">
                <i class="bi bi-${esc(payload.hint.icon)}" aria-hidden="true"></i><b>${esc(payload.hint.text)}</b></span>`
            : '';
        root.innerHTML = `${(payload.cards || []).map(cardHtml).join('')}
            <div class="ga-wb-checks">${title}${buttons}${hint}
                <div class="ga-wb-check-detail" id="${esc(detailId)}" role="region" aria-live="polite" hidden></div>
            </div>`;

        const detail = root.querySelector('.ga-wb-check-detail');
        root.querySelectorAll('[data-check]').forEach((button) => {
            button.addEventListener('click', () => {
                const open = button.getAttribute('aria-expanded') === 'true';
                root.querySelectorAll('[data-check]').forEach((other) => other.setAttribute('aria-expanded', 'false'));
                if (open) {
                    detail.hidden = true;
                    return;
                }
                const check = checks[Number(button.dataset.check)];
                const link = check.url ? `<a href="${esc(check.url)}">${esc(check.link || 'Open')} →</a>` : '';
                detail.innerHTML = `<i class="bi ${checkIcon(check.level)}" aria-hidden="true"></i>
                    <div><b>${unitText(check.title)}</b><span>${unitText(check.detail)}</span>${link}</div>`;
                detail.hidden = false;
                button.setAttribute('aria-expanded', 'true');
            });
        });
    }

    /**
     * The header's "⋯" menu (.ga-wb-more): opens on its button; closes on an item, an outside click or Esc. The
     * page's own buttons live in it with their ids, so their handlers are untouched; an item with `data-proxy`
     * (the phone copies of hidden buttons) clicks the real button instead.
     */
    function wireMenu(menu) {
        if (!menu || menu.dataset.wired) return;
        menu.dataset.wired = '1';
        const toggle = menu.querySelector('[aria-haspopup]');
        const pop = menu.querySelector('.ga-wb-more-pop');
        const close = () => {
            menu.classList.remove('is-open');
            toggle.setAttribute('aria-expanded', 'false');
        };
        toggle.addEventListener('click', (event) => {
            event.stopPropagation();
            const open = !menu.classList.contains('is-open');
            menu.classList.toggle('is-open', open);
            toggle.setAttribute('aria-expanded', String(open));
        });
        pop.addEventListener('click', (event) => {
            const item = event.target.closest('button, a');
            if (!item) return;
            if (item.dataset.proxy) {
                const target = document.getElementById(item.dataset.proxy);
                if (target) target.click();
            }
            close();
        });
        document.addEventListener('click', (event) => {
            if (!menu.contains(event.target)) close();
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') close();
        });
    }

    WB.Summary = WB.Summary || { render };
    WB.wireMenu = WB.wireMenu || wireMenu;
})(window);
