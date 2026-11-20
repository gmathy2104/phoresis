/**
 * GelAnalyzer.Viz.SampleLaneGel — one gel, read-only, with ONE lane put forward: the whole image,
 * every lane outlined and numbered, a veil over everything but that lane, its bands (POI / other),
 * its "L<n> · this sample" pill, the kDa axis of the nearest ladder calibration, and the lane's stored
 * densitometry profile drawn beside the image on the same y scale. One SVG in image-pixel space, so
 * the profile lines up with the gel by construction. Fed by one entry of
 * GET /api/samples/<pk>/gels/ (services/sample_gels.py).
 *
 *   var handle = GelAnalyzer.Viz.SampleLaneGel.mount(el, { entry: entry, dimOthers: true, bandOverlay: true });
 *   handle.update({ dimOthers: false });
 *   handle.destroy();
 *
 * A lane is read by its outline (Rule 2, gel_analyzer/CLAUDE.md): the payload's `outline`, computed by
 * the server (shape.outline_of), through GelAnalyzer.LaneGeometry.outlineOfPayload (shared/lane-geometry.js,
 * loaded first). Its number sits over the middle of the outline's top row, the pill under the middle of its
 * bottom row, and a band without a box is the outline cut at the band's rows (LaneGeometry.slice): a tilted
 * lane's box is wider than the lane and overlaps its neighbours.
 * Two layers: the BASE (slab + photo, or its note) and the viewBox are built once per entry — the image
 * proxy answers no-cache, so a redraw must never re-create the <image> — and the OVERLAY <g> (lanes,
 * numbers, veil, bands, outline, pill, axis, profile) is what render() clears and redraws, on update()
 * and on `dsh:themechange`. Without the image's width and height the photo is NOT drawn (the lane
 * coordinates are display-file pixels: a stretched photo would put the overlay beside the real bands).
 * Colours are --slg-* custom properties (css/sample-lane-gel.css): day / night needs no redraw, but
 * the panel redraws on `dsh:themechange` anyway (cheap, and safe for any measured text).
 */
(function (global) {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';
  var Viz = global.GelAnalyzer && global.GelAnalyzer.Viz;
  var LaneGeometry = global.GelAnalyzer && global.GelAnalyzer.LaneGeometry;
  if (!Viz || !Viz.Panel || !Viz.mount || !LaneGeometry) return;

  function el(tag, attrs, parent) {
    var node = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (parent) parent.appendChild(node);
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function lanePoints(lane) {
    return LaneGeometry.outlineOfPayload(lane);
  }

  // x of the middle of the outline's top row: where the lane's number goes (LaneGeometry.bottomCentre's twin).
  function topCentreX(points) {
    var y = Math.min.apply(null, points.map(function (p) { return p[1]; }));
    var span = LaneGeometry.spanAt(points, y);
    if (span) return (span[0] + span[1]) / 2;
    var e = extent(points);
    return (e.x0 + e.x1) / 2;
  }

  function extent(points) {
    var xs = points.map(function (p) { return p[0]; });
    var ys = points.map(function (p) { return p[1]; });
    return { x0: Math.min.apply(null, xs), x1: Math.max.apply(null, xs), y0: Math.min.apply(null, ys), y1: Math.max.apply(null, ys) };
  }

  function pointsAttr(points) {
    return points.map(function (p) { return p[0] + ',' + p[1]; }).join(' ');
  }

  function imageSize(entry) {
    var w = entry.image && entry.image.width;
    var h = entry.image && entry.image.height;
    if (w && h) return { w: w, h: h };
    var x1 = 1, y1 = 1;
    entry.lanes.forEach(function (lane) {
      var e = extent(lanePoints(lane));
      x1 = Math.max(x1, e.x1);
      y1 = Math.max(y1, e.y1);
    });
    return { w: x1, h: y1 };
  }

  function formatMw(value) {
    return value >= 10 ? String(Math.round(value)) : value.toFixed(1);
  }

  class SampleLaneGelPanel extends Viz.Panel {
    init() {
      this.svg = el('svg', { class: 'ga-slg-svg', role: 'img' }, this.container);
      this._entry = null;
      this._layout = null;
      this.overlay = null;
      this._onWindow('dsh:themechange', () => this.render());
      this.render();
    }

    // The viewBox and the base layer depend only on the entry: built once, not on every redraw.
    _build(entry) {
      var svg = this.svg;
      clear(svg);
      var size = imageSize(entry);
      var W = size.w, H = size.h;
      var fs = Math.max(W, H) / 48;
      var axisW = entry.mw_ticks.length ? fs * 3.4 : fs * 0.6;
      var top = fs * 1.9, bottom = fs * 2.6;
      var gap = fs * 0.8;
      var profileW = W * 0.24;
      svg.setAttribute('viewBox', [-axisW, -top, axisW + W + gap + profileW + fs * 0.6, top + H + bottom].join(' '));
      svg.setAttribute('aria-label', 'Gel ' + (entry.analysis.name || '') + ', lane ' + entry.lane_number + ' outlined');

      el('rect', { x: 0, y: 0, width: W, height: H, class: 'ga-slg-slab' }, svg);
      var sized = !!(entry.image && entry.image.width && entry.image.height);
      if (entry.image && entry.image.url && sized) {
        el('image', { href: entry.image.url, x: 0, y: 0, width: W, height: H, preserveAspectRatio: 'none' }, svg);
      } else {
        var missing = el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', class: 'ga-slg-note', 'font-size': fs }, svg);
        missing.textContent = entry.image && entry.image.url ? 'image size unknown' : 'no display image';
      }

      this.overlay = el('g', { class: 'ga-slg-overlay' }, svg);
      this._layout = { W: W, H: H, fs: fs, gap: gap, profileW: profileW };
      this._entry = entry;
    }

    render() {
      var entry = this.options.entry;
      if (!entry) {
        clear(this.svg);
        this._entry = null;
        this.overlay = null;
        return;
      }
      if (entry !== this._entry) this._build(entry);
      var svg = this.overlay;
      clear(svg);

      var W = this._layout.W, H = this._layout.H, fs = this._layout.fs;
      var gap = this._layout.gap, profileW = this._layout.profileW;

      var self = null;
      entry.lanes.forEach(function (lane) { if (lane.id === entry.lane_id) self = lane; });
      var selfPts = self ? lanePoints(self) : null;

      entry.lanes.forEach(function (lane) {
        var pts = lanePoints(lane);
        if (lane.id !== entry.lane_id) el('polygon', { points: pointsAttr(pts), class: 'ga-slg-lane' }, svg);
        // Above the image, over the middle of the lane's top row: a tilted lane's box centre sits beside it.
        var number = el('text', {
          x: topCentreX(pts),
          y: -fs * 0.5,
          'text-anchor': 'middle',
          'font-size': fs * (lane.id === entry.lane_id ? 0.95 : 0.8),
          class: lane.id === entry.lane_id ? 'ga-slg-lane-num is-self' : 'ga-slg-lane-num',
        }, svg);
        number.textContent = lane.lane_type === 'LADDER' ? 'MW' : String(lane.lane_number);
      });

      if (this.options.dimOthers !== false && selfPts) {
        var hole = 'M' + selfPts.map(function (p) { return p[0] + ',' + p[1]; }).join(' L') + ' Z';
        el('path', { d: 'M0,0 H' + W + ' V' + H + ' H0 Z ' + hole, 'fill-rule': 'evenodd', class: 'ga-slg-veil' }, svg);
      }

      if (this.options.bandOverlay !== false && selfPts) {
        var laneRows = extent(selfPts);
        entry.bands.forEach(function (band) {
          if (band.band_type !== 'POI' && band.band_type !== 'OTHER') return;
          var cls = band.band_type === 'POI' ? 'ga-slg-band is-poi' : 'ga-slg-band';
          var b = band.bbox;
          if (b) {
            el('rect', { x: b.x, y: b.y, width: b.width, height: b.height, rx: fs * 0.15, class: cls }, svg);
            return;
          }
          // No box: the lane's outline cut at the band's rows (kept inside the lane), never the box's full width.
          var y0 = Math.max(band.position_y - fs * 0.25, laneRows.y0);
          var y1 = Math.min(band.position_y + fs * 0.25, laneRows.y1);
          var cut = y1 > y0 ? LaneGeometry.slice(selfPts, y0, y1) : null;
          if (cut) el('polygon', { points: pointsAttr(cut), class: cls }, svg);
        });
      }

      if (selfPts) {
        el('polygon', { points: pointsAttr(selfPts), class: 'ga-slg-self' }, svg);
        var label = 'L' + entry.lane_number + ' · this sample';
        var pillH = fs * 1.5;
        var pillW = fs * 0.58 * label.length + fs;
        // Under the image, centred on the middle of the lane's bottom row (the row nearest the pill).
        var bottomX = LaneGeometry.bottomCentre(selfPts)[0];
        var px = Math.min(Math.max(bottomX - pillW / 2, 0), Math.max(W - pillW, 0));
        el('rect', { x: px, y: H + fs * 0.6, width: pillW, height: pillH, rx: pillH / 2, class: 'ga-slg-pill' }, svg);
        var pillText = el('text', { x: px + pillW / 2, y: H + fs * 0.6 + pillH * 0.7, 'text-anchor': 'middle', 'font-size': fs * 0.9, class: 'ga-slg-pill-text' }, svg);
        pillText.textContent = label;
      }

      if (entry.mw_ticks.length) {
        var kda = el('text', { x: -fs * 0.6, y: -fs * 0.5, 'text-anchor': 'end', 'font-size': fs * 0.85, class: 'ga-slg-axis-title' }, svg);
        kda.textContent = 'kDa';
        entry.mw_ticks.forEach(function (tick) {
          el('line', { x1: -fs * 0.5, x2: 0, y1: tick.y, y2: tick.y, class: 'ga-slg-tick' }, svg);
          var t = el('text', { x: -fs * 0.7, y: tick.y + fs * 0.32, 'text-anchor': 'end', 'font-size': fs * 0.85, class: 'ga-slg-axis' }, svg);
          t.textContent = formatMw(tick.mw_kda);
        });
      }

      var px0 = W + gap;
      el('line', { x1: px0, x2: px0, y1: 0, y2: H, class: 'ga-slg-tick' }, svg);
      var profile = entry.profile;
      if (profile && profile.y.length) {
        var max = 0;
        profile.intensity.forEach(function (v) { if (v > max) max = v; });
        max = max || 1;
        var X = function (v) { return px0 + Math.max(v, 0) / max * profileW; };
        entry.bands.forEach(function (band) {
          if (band.band_type !== 'POI' || !band.bbox) return;
          var y0 = band.bbox.y, y1 = band.bbox.y + band.bbox.height;
          var seg = [];
          profile.y.forEach(function (y, i) { if (y >= y0 && y <= y1) seg.push([X(profile.intensity[i]), y]); });
          if (seg.length < 2) return;
          var d = 'M' + px0 + ',' + seg[0][1] + seg.map(function (p) { return ' L' + p[0].toFixed(1) + ',' + p[1]; }).join('') + ' L' + px0 + ',' + seg[seg.length - 1][1] + ' Z';
          el('path', { d: d, class: 'ga-slg-profile-poi' }, svg);
        });
        var line = profile.y.map(function (y, i) { return (i ? 'L' : 'M') + X(profile.intensity[i]).toFixed(1) + ',' + y; }).join(' ');
        el('path', { d: line, class: 'ga-slg-profile' }, svg);
        var caption = el('text', { x: px0 + profileW / 2, y: H + fs * 1.6, 'text-anchor': 'middle', 'font-size': fs * 0.8, class: 'ga-slg-note' }, svg);
        caption.textContent = 'lane profile';
      } else {
        var cx = px0 + profileW / 2, cy = H / 2;
        var none = el('text', { x: cx, y: cy, 'text-anchor': 'middle', 'font-size': fs * 0.85, transform: 'rotate(-90 ' + cx + ' ' + cy + ')', class: 'ga-slg-note' }, svg);
        none.textContent = 'no densitometry yet';
      }
    }
  }

  global.GelAnalyzer.Viz.SampleLaneGel = {
    Panel: SampleLaneGelPanel,
    mount: function (containerEl, cfg) {
      var handle = Viz.mount(containerEl, {
        panelDefs: [{ name: 'gel', PanelClass: SampleLaneGelPanel, containerClass: 'ga-slg' }],
        options: { entry: cfg.entry, dimOthers: cfg.dimOthers !== false, bandOverlay: cfg.bandOverlay !== false },
      });
      return {
        update: function (opts) {
          var panel = handle.getPanel('gel');
          Object.keys(opts || {}).forEach(function (key) { panel.options[key] = opts[key]; });
          panel.render();
        },
        destroy: function () { handle.destroy(); },
      };
    },
  };
})(window);
