/**
 * ReadingCard - "How this gel is read", at the top of the annotation editor's properties (slice 3c).
 *
 * Renders the server's reading (/data/ page_summary, `analysis_detail.summary_payload`): what a band counts as on
 * this assay (`guide`: by type on a purity, by role on a western -- the swatch of the band form's role line) and the
 * checks annotating can answer (`annotation_checks`), worst first, each opening
 * its detail and its link on a click or a tap. Every word is the server's; this file only lays them out (spec I2).
 * Re-rendered on READING_CHANGED (a load, a reload, a refresh after a server write).
 */

(function (global) {
    'use strict';

    const Events = global.GelViewer.Events;
    const COLLAPSED_KEY = 'gv-reading-collapsed';

    // The guide's swatch names -> the workbench colour tokens (night / day by the theme).
    const SWATCH_TOKENS = {
        'b-poi': '--ga-wb-b-poi',
        'b-other': '--ga-wb-b-other',
        'b-mw': '--ga-wb-b-mw',
        'z-aggregate': '--ga-wb-z-aggregate',
        'z-main': '--ga-wb-z-main',
        'z-clipping': '--ga-wb-z-clipping',
    };

    function escapeHtml(value) {
        const d = document.createElement('div');
        d.textContent = value == null ? '' : String(value);
        return d.innerHTML.replace(/"/g, '&quot;');
    }

    function swatch(name) {
        if (name === 'ref') return '<span class="gv-reading-ref" aria-hidden="true">REF</span>';
        if (name === 'left-out') return '<i class="gv-reading-sw gv-reading-sw--hatch" aria-hidden="true"></i>';
        const token = SWATCH_TOKENS[name];
        return `<i class="gv-reading-sw" aria-hidden="true"${token ? ` style="background: var(${token})"` : ''}></i>`;
    }

    function readCollapsed() {
        try {
            return global.localStorage.getItem(COLLAPSED_KEY) === '1';
        } catch (e) {
            return false;
        }
    }

    function writeCollapsed(collapsed) {
        try {
            global.localStorage.setItem(COLLAPSED_KEY, collapsed ? '1' : '0');
        } catch (e) {
            // A private window or blocked storage: the card simply opens expanded next time.
        }
    }

    class ReadingCard {
        /**
         * @param {Object} options
         * @param {EventBus} options.eventBus
         * @param {HTMLElement} options.container - #reading-card
         */
        constructor(options) {
            this.eventBus = options.eventBus;
            this.container = options.container;
            this.collapsed = readCollapsed();
            if (!this.container) return;
            this.eventBus.on(Events.READING_CHANGED, (reading) => this.render(reading));
        }

        render(reading) {
            if (!this.container) return;
            const open = new Set(
                Array.from(this.container.querySelectorAll('.gv-reading-check[aria-expanded="true"]'))
                    .map((button) => button.dataset.kind)
            );
            // A refresh rebuilds the card: the keyboard focus goes back to the same control.
            const active = document.activeElement;
            let focused = null;
            if (active && this.container.contains(active)) {
                const kind = active.closest('.gv-reading-check-row')?.querySelector('.gv-reading-check')?.dataset.kind;
                const check = kind ? `.gv-reading-check[data-kind="${CSS.escape(kind)}"]` : null;
                if (active.classList.contains('gv-reading-toggle')) focused = '.gv-reading-toggle';
                else if (check && active.tagName === 'A') focused = `${check} + .gv-reading-detail a`;
                else focused = check;
            }

            if (!reading) {
                this.container.innerHTML = `
                    <div class="gv-reading-head"><span class="gv-reading-title"><i class="bi bi-eyedropper" aria-hidden="true"></i>How this gel is read</span></div>
                    <p class="gv-reading-none">Reading unavailable: reload the page to read it again.</p>`;
                return;
            }

            const guide = (reading.guide || []).map((item) => `
                <li>${swatch(item.swatch)}<span><b>${escapeHtml(item.label)}</b> <span class="gv-reading-text">— ${escapeHtml(item.text)}</span></span></li>`).join('');

            const here = global.location ? global.location.pathname : '';
            const checks = (reading.annotation_checks || []).map((check) => {
                const level = check.level === 'warn' ? 'warn' : 'info';
                const icon = level === 'warn' ? 'bi-exclamation-triangle-fill' : 'bi-info-circle-fill';
                const expanded = open.has(check.kind);
                // A link to the page already open (Annotate) is left out: the detail says what to do here.
                const link = check.url && check.url !== here
                    ? ` <a href="${escapeHtml(check.url)}">${escapeHtml(check.link || 'Open')}</a>` : '';
                return `
                    <div class="gv-reading-check-row is-${level}">
                        <button type="button" class="gv-reading-check" data-kind="${escapeHtml(check.kind)}" aria-expanded="${expanded}">
                            <i class="bi ${icon}" aria-hidden="true"></i><span>${escapeHtml(check.title)}</span>
                        </button>
                        <p class="gv-reading-detail"${expanded ? '' : ' hidden'}>${escapeHtml(check.detail)}${link}</p>
                    </div>`;
            }).join('');

            this.container.classList.toggle('is-collapsed', this.collapsed);
            this.container.innerHTML = `
                <div class="gv-reading-head">
                    <button type="button" class="gv-reading-toggle" aria-expanded="${!this.collapsed}" aria-controls="reading-card-body">
                        <span class="gv-reading-title"><i class="bi bi-eyedropper" aria-hidden="true"></i>How this gel is read · ${escapeHtml(reading.assay_label)}</span>
                        <i class="bi bi-chevron-down gv-reading-chevron" aria-hidden="true"></i>
                    </button>
                </div>
                <div class="gv-reading-body" id="reading-card-body"${this.collapsed ? ' hidden' : ''}>
                    <ul class="gv-reading-guide">${guide}</ul>
                    <div class="gv-reading-checks">${checks || '<p class="gv-reading-none">Nothing to check for the annotation.</p>'}</div>
                </div>`;

            // Folded in place (never re-rendered): the button keeps the keyboard focus.
            const toggle = this.container.querySelector('.gv-reading-toggle');
            const body = this.container.querySelector('.gv-reading-body');
            toggle.addEventListener('click', () => {
                this.collapsed = !this.collapsed;
                writeCollapsed(this.collapsed);
                toggle.setAttribute('aria-expanded', String(!this.collapsed));
                body.hidden = this.collapsed;
                this.container.classList.toggle('is-collapsed', this.collapsed);
            });
            this.container.querySelectorAll('.gv-reading-check').forEach((button) => {
                button.addEventListener('click', () => {
                    const detail = button.parentElement.querySelector('.gv-reading-detail');
                    const expanded = button.getAttribute('aria-expanded') !== 'true';
                    button.setAttribute('aria-expanded', String(expanded));
                    if (detail) detail.hidden = !expanded;
                });
            });
            if (focused) this.container.querySelector(focused)?.focus({ preventScroll: true });
        }
    }

    global.GelViewer = global.GelViewer || {};
    global.GelViewer.ReadingCard = ReadingCard;

})(window);
