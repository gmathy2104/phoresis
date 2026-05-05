/**
 * GelPreview — read-only annotated gel viewer for analysis detail pages.
 *
 * Renders the gel image with an SVG overlay showing lane outlines (typed
 * colour) and band shapes (typed colour). No editing, no panels — just a
 * "well-presented snapshot" for the analysis detail view.
 *
 * Click on a lane → emits a `gelpreview:lane-clicked` CustomEvent on the
 * container so other components (e.g. lane spreadsheet) can sync highlight.
 *
 * Depends on SVG.js (vendored at gel_analyzer/js/vendor/svg.min.js).
 *
 * Usage:
 *   new GelPreview({
 *       container: document.getElementById('gel-preview'),
 *       imageUrl: '/api/gels/<uuid>/proxy/',
 *       imageWidth: 800,
 *       imageHeight: 600,
 *       lanes: [...],   // lane_to_dict() objects with nested bands[]
 *   });
 */
(function(global) {
    'use strict';

    var LANE_TYPE_CLASS = {
        SAMPLE: 'sample',
        LADDER: 'ladder',
        CONTROL: 'control',
        EMPTY: 'empty',
        DOT: 'sample',
    };
    var BAND_TYPE_CLASS = {
        POI: 'poi',
        MW_REFERENCE: 'mw_reference',
        OTHER: 'other',
    };

    function GelPreview(opts) {
        this.container = opts.container;
        this.imageUrl = opts.imageUrl;
        this.imageWidth = opts.imageWidth || 800;
        this.imageHeight = opts.imageHeight || 600;
        this.lanes = opts.lanes || [];
        this._init();
    }

    GelPreview.prototype._init = function() {
        var self = this;
        this.container.classList.add('gp-root');
        this.container.innerHTML =
            '<div class="gp-stage gp-stage--inline" data-role="inline-stage" style="aspect-ratio:' + this.imageWidth + ' / ' + this.imageHeight + '">' +
                '<img class="gp-image" alt="Annotated gel">' +
                '<svg class="gp-overlay" viewBox="0 0 ' + this.imageWidth + ' ' + this.imageHeight + '" preserveAspectRatio="xMidYMid meet"></svg>' +
                '<span class="gp-zoom-hint"><i class="bi bi-zoom-in"></i> Click to enlarge</span>' +
            '</div>' +
            '<div class="gp-legend">' +
                this._legendItem('sample', 'Sample') +
                this._legendItem('ladder', 'Ladder') +
                this._legendItem('control', 'Control') +
                this._legendItem('empty', 'Empty') +
                '<span class="gp-legend-sep"></span>' +
                this._legendBand('poi', 'POI') +
                this._legendBand('mw_reference', 'MW marker') +
                this._legendBand('other', 'Other band') +
            '</div>';

        this.inlineStage = this.container.querySelector('[data-role="inline-stage"]');
        var img = this.inlineStage.querySelector('.gp-image');
        img.src = this.imageUrl;

        this.tooltip = document.createElement('div');
        this.tooltip.className = 'gp-tooltip';
        this.tooltip.hidden = true;

        this.svg = SVG(this.inlineStage.querySelector('.gp-overlay'));
        this.lanesGroup = this.svg.group().addClass('gp-lanes');
        this.bandsGroup = this.svg.group().addClass('gp-bands');

        // Render after image dimensions are known to avoid flash
        if (img.complete) {
            this._renderAll();
        } else {
            img.addEventListener('load', function() { self._renderAll(); }, { once: true });
        }

        // Click anywhere on the inline stage → open modal with interactive overlay
        this.inlineStage.addEventListener('click', function() { self._openModal(); });
    };

    GelPreview.prototype._openModal = function() {
        var self = this;
        if (this.modal) {
            this.modal.hidden = false;
            return;
        }
        var modal = document.createElement('div');
        modal.className = 'gp-modal';
        modal.innerHTML =
            '<button type="button" class="gp-modal-close" aria-label="Close"><i class="bi bi-x-lg"></i></button>' +
            '<div class="gp-stage gp-stage--modal" data-role="modal-stage" style="aspect-ratio:' + this.imageWidth + ' / ' + this.imageHeight + '">' +
                '<img class="gp-image" alt="Annotated gel" src="' + this.imageUrl + '">' +
                '<svg class="gp-overlay" viewBox="0 0 ' + this.imageWidth + ' ' + this.imageHeight + '" preserveAspectRatio="xMidYMid meet"></svg>' +
            '</div>';
        document.body.appendChild(modal);
        modal.appendChild(this.tooltip);

        var modalSvg = SVG(modal.querySelector('.gp-overlay'));
        var lg = modalSvg.group();
        var bg = modalSvg.group();
        // Re-render shapes into modal overlay (interactive)
        var prevLanes = this.lanesGroup, prevBands = this.bandsGroup;
        this.lanesGroup = lg;
        this.bandsGroup = bg;
        this._renderAll();
        this.lanesGroup = prevLanes;
        this.bandsGroup = prevBands;

        function close() { modal.hidden = true; self._hideTooltip(); }
        modal.querySelector('.gp-modal-close').addEventListener('click', function(e) { e.stopPropagation(); close(); });
        modal.addEventListener('click', function(e) { if (e.target === modal) close(); });
        document.addEventListener('keydown', function onKey(e) {
            if (e.key === 'Escape' && !modal.hidden) { close(); }
        });

        this.modal = modal;
    };

    GelPreview.prototype._legendItem = function(cls, label) {
        return '<span class="gp-legend-item"><span class="gp-legend-swatch gv-lane ' + cls + '"></span>' + label + '</span>';
    };
    GelPreview.prototype._legendBand = function(cls, label) {
        return '<span class="gp-legend-item"><span class="gp-legend-swatch gv-band ' + cls + '"></span>' + label + '</span>';
    };

    GelPreview.prototype._renderAll = function() {
        var self = this;
        this.lanes.forEach(function(lane) {
            self._renderLane(lane);
            (lane.bands || []).forEach(function(band) {
                self._renderBand(band, lane);
            });
        });
    };

    GelPreview.prototype._renderLane = function(lane) {
        var self = this;
        var typeCls = LANE_TYPE_CLASS[lane.lane_type] || 'sample';
        var shape;

        if (lane.lane_shape && lane.lane_shape !== 'RECTANGLE' && lane.polygon && lane.polygon.length >= 3) {
            shape = this.lanesGroup.polygon(lane.polygon);
        } else {
            shape = this.lanesGroup.rect(lane.width, lane.height).move(lane.x, lane.y);
        }
        shape.addClass('gv-lane').addClass(typeCls).attr('data-lane-id', lane.id);

        // Lane number label
        var labelX, labelY;
        if (lane.polygon && lane.polygon.length > 0) {
            labelX = Math.min.apply(null, lane.polygon.map(function(p) { return p[0]; })) + 4;
            labelY = Math.min.apply(null, lane.polygon.map(function(p) { return p[1]; })) + 4;
        } else {
            labelX = lane.x + 4;
            labelY = lane.y + 4;
        }
        var fontSize = Math.max(10, Math.min(lane.width || 50, 28) * 0.55);
        this.lanesGroup.text(String(lane.lane_number))
            .move(labelX, labelY)
            .font({ size: fontSize, weight: 700, family: 'Inter, system-ui, sans-serif' })
            .fill('#0f172a')
            .attr('paint-order', 'stroke')
            .attr('stroke', '#fff')
            .attr('stroke-width', 2)
            .attr('pointer-events', 'none');

        // Hover/click interactions
        var node = shape.node;
        node.addEventListener('mouseenter', function(e) { self._showTooltip(e, self._laneTooltip(lane)); });
        node.addEventListener('mousemove', function(e) { self._moveTooltip(e); });
        node.addEventListener('mouseleave', function() { self._hideTooltip(); });
        node.addEventListener('click', function() {
            self.container.dispatchEvent(new CustomEvent('gelpreview:lane-clicked', {
                detail: { laneId: lane.id, laneNumber: lane.lane_number },
                bubbles: true,
            }));
        });
    };

    GelPreview.prototype._renderBand = function(band, lane) {
        var self = this;
        var typeCls = BAND_TYPE_CLASS[band.band_type] || 'other';
        var shape;

        if (band.polygon && band.polygon.length >= 3) {
            shape = this.bandsGroup.polygon(band.polygon);
        } else if (band.bbox_x != null && band.bbox_width != null) {
            shape = this.bandsGroup.rect(band.bbox_width, band.bbox_height).move(band.bbox_x, band.bbox_y);
        } else {
            return;
        }
        shape.addClass('gv-band').addClass(typeCls).attr('data-band-id', band.id);

        var node = shape.node;
        node.addEventListener('mouseenter', function(e) { self._showTooltip(e, self._bandTooltip(band, lane)); });
        node.addEventListener('mousemove', function(e) { self._moveTooltip(e); });
        node.addEventListener('mouseleave', function() { self._hideTooltip(); });
    };

    GelPreview.prototype._laneTooltip = function(lane) {
        var parts = ['<strong>Lane ' + lane.lane_number + '</strong>'];
        if (lane.lane_type_display) parts.push(lane.lane_type_display);
        if (lane.sample_name) parts.push(this._escape(lane.sample_name));
        if (lane.condition_display && lane.condition_display !== '—') parts.push(this._escape(lane.condition_display));
        if (lane.protein_load_ug) parts.push(lane.protein_load_ug.toFixed(1) + ' µg');
        if (lane.bands && lane.bands.length) parts.push(lane.bands.length + ' band' + (lane.bands.length > 1 ? 's' : ''));
        return parts.join('<br>');
    };

    GelPreview.prototype._bandTooltip = function(band, lane) {
        var parts = ['<strong>' + (band.band_type_display || 'Band') + '</strong>'];
        parts.push('Lane ' + lane.lane_number);
        if (band.label) parts.push(this._escape(band.label));
        if (band.estimated_mw_kda) parts.push(band.estimated_mw_kda.toFixed(1) + ' kDa');
        return parts.join('<br>');
    };

    GelPreview.prototype._showTooltip = function(e, html) {
        this.tooltip.innerHTML = html;
        this.tooltip.hidden = false;
        this._moveTooltip(e);
    };
    GelPreview.prototype._moveTooltip = function(e) {
        var parent = this.tooltip.parentElement || this.container;
        var rect = parent.getBoundingClientRect();
        var x = e.clientX - rect.left + 12;
        var y = e.clientY - rect.top + 12;
        this.tooltip.style.left = x + 'px';
        this.tooltip.style.top = y + 'px';
    };
    GelPreview.prototype._hideTooltip = function() {
        this.tooltip.hidden = true;
    };

    GelPreview.prototype._escape = function(s) {
        return String(s).replace(/[&<>"']/g, function(c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    };

    global.GelPreview = GelPreview;

})(window);
