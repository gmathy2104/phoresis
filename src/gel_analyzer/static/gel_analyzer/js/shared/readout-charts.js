/**
 * Readout charts — a western readout drawn one bar per lane (GelAnalyzer.ReadoutCharts)
 *
 * The densitometry page's readout tab (js/densitometry/panels/readout-panel.js) and the gel comparison's
 * (js/sample-comparison/panels/poi-purity-panel.js) draw the same charts from the server's values: this
 * file holds them, so the two pages cannot drift. HTML/CSS bars, themed by the --ga-wb-* tokens
 * (css/ga-workbench.css) and the .dm-ro-* rules (css/densitometry.css).
 *
 *   hcp(entries, opts)       Anti-HCP: the lane's HCP signal in % of ITS reference lane's, on a log axis
 *                            (0.1–1000 %) with a line at 100 %. Without a reference value, the raw signal
 *                            (a.u.) on a linear axis — only when opts.signalComparable (one blot): an
 *                            exposure-dependent signal is never compared across membranes.
 *   variants(entries, opts)  Anti-molecule: one stacked bar per lane, HMWS | Main band | LMWS
 *                            (high / low molecular weight species), in gel order.
 *
 * An entry: { values, reason, is_reference, carries? } — `values` the server's numbers (null, or {}, when
 * the lane has none: its reason is shown, muted, never a zero); `carries === false` (the comparison's
 * ladders and non-reference controls) prints "—". opts.label(entry) returns the lane's label HTML
 * (escaped by the caller). The charts never compute a readout.
 */
(function (global) {
    'use strict';

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function isNum(v) {
        return v !== null && v !== undefined && isFinite(v);
    }

    // 1 decimal for a percentage, thousands separator for arbitrary units.
    function fmtPercent(v) {
        return `${Number(v).toFixed(1)} %`;
    }

    function fmtSignal(v) {
        return Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 });
    }

    function muted(text) {
        return `<span class="dm-readout-muted">${esc(text)}</span>`;
    }

    /** The entry's values, or null: a lane that does not carry the readout, or has no value yet. */
    function valuesOf(entry) {
        if (!entry || entry.carries === false) return null;
        const v = entry.values;
        return v && Object.keys(v).length ? v : null;
    }

    /** The muted text of a lane with no value: "—" when it does not carry the readout. */
    function whyNot(entry, fallback) {
        if (entry && entry.carries === false) return '—';
        return (entry && entry.reason) || fallback;
    }

    function hcp(entries, opts) {
        opts = opts || {};
        const label = opts.label || (() => '');
        const signalComparable = opts.signalComparable !== false;
        const percentOf = (entry) => {
            const v = valuesOf(entry);
            return v && isNum(v.hcp_signal_vs_reference_percent) ? v.hcp_signal_vs_reference_percent : null;
        };
        const byPercent = entries.some((entry) => percentOf(entry) !== null);
        const drawSignal = !byPercent && signalComparable;
        const signals = entries.map((entry) => {
            const v = valuesOf(entry);
            return v && isNum(v.hcp_total_signal) ? v.hcp_total_signal : 0;
        });
        const maxSignal = Math.max(1, ...signals);
        const LO = Math.log10(0.1);
        const HI = Math.log10(1000);
        const logPos = (x) => Math.max(0, Math.min(100, ((Math.log10(Math.max(0.1, x)) - LO) / (HI - LO)) * 100));

        const rows = entries.map((entry) => {
            const v = valuesOf(entry);
            const rowClass = `dm-ro-row${entry.is_reference ? ' is-reference' : ''}`;
            if (!v) {
                return `<div class="${rowClass}">${label(entry)}<div class="dm-ro-track">${muted(whyNot(entry, 'no value'))}</div></div>`;
            }
            const excluded = v.poi_band_count > 0 ? ` · ${muted(`+${v.poi_band_count} POI excluded`)}` : '';
            const bands = `${esc(v.band_count ?? 0)} HCP band${v.band_count === 1 ? '' : 's'}${excluded}`;
            let bar;
            let value;
            if (byPercent) {
                const percent = percentOf(entry);
                if (percent === null) {
                    bar = '';
                    value = muted(entry.reason || 'no reference lane');
                } else {
                    bar = `<span class="dm-ro-bar${entry.is_reference ? ' is-reference' : ''}" style="width:${logPos(percent).toFixed(1)}%"></span>`;
                    value = `<b>${fmtPercent(percent)}</b>`;
                }
            } else if (drawSignal) {
                const width = isNum(v.hcp_total_signal) ? (v.hcp_total_signal / maxSignal) * 100 : 0;
                bar = `<span class="dm-ro-bar" style="width:${width.toFixed(1)}%"></span>`;
                value = `<b>${isNum(v.hcp_total_signal) ? fmtSignal(v.hcp_total_signal) : '—'}</b> a.u.`;
            } else {
                bar = '';
                value = muted(entry.reason || 'no reference lane');
            }
            return `<div class="${rowClass}">${label(entry)}
                <div class="dm-ro-track">${bar}</div>
                <div class="dm-ro-value">${value}<small>${bands}</small></div></div>`;
        }).join('');

        const axis = byPercent
            ? `<div class="dm-ro-axis"><span style="left:0">0.1 %</span><span style="left:25%">1 %</span><span style="left:50%">10 %</span><span style="left:75%">100 %</span><span style="left:100%">1000 %</span></div>
               <div class="dm-ro-refline" style="left:75%" title="The reference lane reads 100 %"></div>`
            : '';
        let legend;
        if (byPercent) {
            legend = '<span><i class="ga-wb-sw" style="background:var(--ga-wb-b-other)"></i>HCP signal in % of the reference lane\'s · log scale</span>';
        } else if (drawSignal) {
            legend = '<span class="dm-ro-warn"><i class="bi bi-exclamation-triangle-fill"></i> No HCP % of reference: the raw signal (a.u.) is shown.</span>';
        } else {
            legend = '<span class="dm-ro-warn"><i class="bi bi-exclamation-triangle-fill"></i> No HCP % of reference, and these lanes come from different blots: their signals (a.u.) are not comparable.</span>';
        }
        const note = opts.note || `% of ref. = the lane's HCP signal ÷ the reference lane's, on the same membrane.
                The signal in a.u. depends on the exposure: compare it within this blot only.
                POI bands (cross-reacting molecule) are left out of the HCP signal.`;

        return `
            <div class="dm-ro-legend">${legend}</div>
            <div class="dm-ro-chart${byPercent ? ' has-axis' : ''}"><div class="dm-ro-plot">${axis}</div>${rows}</div>
            <p class="dm-readout-note">${note}</p>`;
    }

    function variants(entries, opts) {
        opts = opts || {};
        const label = opts.label || (() => '');
        const parts = [
            ['aggregate_percent', 'aggregate', 'HMWS'],
            ['main_band_percent', 'main', 'Main band'],
            ['fragment_percent', 'clipping', 'LMWS'],
        ];
        const rows = entries.map((entry) => {
            const v = valuesOf(entry);
            if (!v || !isNum(v.main_band_percent)) {
                return `<div class="dm-ro-row">${label(entry)}<div class="dm-ro-track">${muted(whyNot(entry, 'no POI band'))}</div></div>`;
            }
            const segments = parts.map(([key, role, name]) => {
                const x = isNum(v[key]) ? v[key] : 0;
                const text = x >= 7 ? `<em>${x.toFixed(1)}</em>` : '';
                return `<span class="dm-ro-seg dm-ro-seg--${role}" style="width:${x}%" title="${name} ${fmtPercent(x)}">${text}</span>`;
            }).join('');
            const values = parts.map(([key, , name]) => `${name} ${isNum(v[key]) ? fmtPercent(v[key]) : '—'}`).join(' · ');
            return `<div class="dm-ro-row">${label(entry)}
                <div class="dm-ro-track dm-ro-track--stack">${segments}</div>
                <div class="dm-ro-value"><small>${esc(values)}</small></div></div>`;
        }).join('');
        return `
            <div class="dm-ro-legend">
                <span><i class="ga-wb-sw" style="background:var(--ga-wb-z-aggregate)"></i>HMWS — high molecular weight species, above the POI band</span>
                <span><i class="ga-wb-sw" style="background:var(--ga-wb-z-main)"></i>Main band</span>
                <span><i class="ga-wb-sw" style="background:var(--ga-wb-z-clipping)"></i>LMWS — low molecular weight species, below the POI band</span>
            </div>
            <div class="dm-ro-chart">${rows}</div>
            <p class="dm-readout-note">In % of the lane's counted signal (POI and other bands): above the POI band =
                HMWS, on it = main band, below it = LMWS.</p>`;
    }

    global.GelAnalyzer = global.GelAnalyzer || {};
    global.GelAnalyzer.ReadoutCharts = { hcp, variants, esc, isNum, fmtPercent, muted };
})(window);
