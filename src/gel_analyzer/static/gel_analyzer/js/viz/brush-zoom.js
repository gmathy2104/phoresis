/**
 * GelAnalyzer.Viz.BrushZoom — the zoom gesture shared by the Viz layers' curve panels.
 *
 * Brush a range on X, and Y re-fits to what the window shows (the panel computes
 * that domain with fitY). A double-click on the plot, or a click on the
 * "Reset zoom" badge, returns to the full view. The panel keeps the window in
 * DATA units and redraws from it, so a resize, a mode switch or a remount
 * (PD dashboard: theme / style change) draws the same window again.
 *
 *   var zoomUi = BrushZoom.attachX(layer, {
 *     xScale, width, height,          // or getXScale() for a persistent SVG
 *     zoomed: !!this._zoomX,          // shows the Reset badge (zoomUi.setZoomed later)
 *     onZoom: function (domain) {},   // [x0, x1] in data units, in pixel order
 *     onReset: function () {},
 *     onHover: function (event, mx) {}, onLeave: function () {},
 *     onClick: function (event, mx) {}, // optional: a press-and-release that drew no window
 *     badgeAt: 'left',                // optional, default top right of the plot
 *   });
 *
 * onClick exists because d3's brush owns the overlay: a click on a point never
 * reaches the point (it ends a brush gesture with no selection). Panels that
 * do not pass it are unchanged.
 *
 * `layer` is a <g> in plot coordinates, appended AFTER the traces: the hover
 * handlers live on the brush's own overlay. A separate hover <rect> on top of
 * the brush swallows every mousedown and the brush never starts.
 */
(function (global) {
  'use strict';

  global.GelAnalyzer = global.GelAnalyzer || {};
  global.GelAnalyzer.Viz = global.GelAnalyzer.Viz || {};

  // A brush narrower than this is a slip of the hand, not a window.
  var MIN_BRUSH_PX = 5;

  // Badge colours, per mode (the PD dashboard remounts its tiles on
  // dsh:themechange, so reading the mode at draw time is enough).
  var BADGE = {
    dark: { fill: 'rgba(15, 23, 42, 0.88)', stroke: 'rgba(96, 165, 250, 0.55)', text: '#e2e8f0', hint: '#94a3b8' },
    light: { fill: 'rgba(255, 255, 255, 0.94)', stroke: 'rgba(37, 99, 235, 0.5)', text: '#1e3a8a', hint: '#475569' },
  };

  function isDay() {
    return document.documentElement.getAttribute('data-theme') === 'light';
  }

  /**
   * Keep a press inside the chart from reaching a host drag handler: d3's brush
   * stops propagation only when the gesture ENDS, so on the PD dashboard the
   * press would also start Gridstack's tile drag (it listens on the enclosing
   * .grid-stack-item-content). No-op standalone.
   * user-select: a press-and-move below the brush's threshold leaves a text
   * selection on the tick labels, and the next press inside it starts a native
   * drag that cancels the gesture.
   */
  function guard(svgNode) {
    if (!svgNode || svgNode.__bzGuarded) return;
    svgNode.__bzGuarded = true;
    ['mousedown', 'pointerdown', 'touchstart'].forEach(function (type) {
      svgNode.addEventListener(type, function (event) { event.stopPropagation(); });
    });
    svgNode.style.userSelect = 'none';
    svgNode.style.webkitUserSelect = 'none';
  }

  /**
   * Y domain for the visible window. values = the Y of every point whose X lies
   * inside it. zeroBased (distributions): [min(0, lo), hi + 10 %]; otherwise the
   * visible range padded by 5 % on each side. null when nothing is visible, so the
   * panel keeps its full-view domain.
   */
  function fitY(values, zeroBased) {
    var lo = Infinity;
    var hi = -Infinity;
    for (var i = 0; i < values.length; i++) {
      var v = values[i];
      if (v == null || isNaN(v)) continue;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    if (hi === -Infinity) return null;
    if (zeroBased) {
      lo = Math.min(0, lo);
      return [lo, hi > lo ? hi + (hi - lo) * 0.1 : lo + 1];
    }
    var pad = (hi - lo) * 0.05 || Math.abs(hi) * 0.05 || 1;
    return [lo - pad, hi + pad];
  }

  // The badge: "↺ Reset zoom" while zoomed, else a "Drag to zoom" hint shown only
  // while the pointer is over the plot (and never in the way of the brush).
  // Redrawn in place by setZoomed() for a panel that keeps its SVG across zooms.
  function renderBadge(badge, opts, zoomed, hovering) {
    var colors = isDay() ? BADGE.light : BADGE.dark;
    var left = opts.badgeAt === 'left';
    badge.selectAll('*').remove();
    badge
      .attr('transform', 'translate(' + (left ? 6 : opts.width - 6) + ',6)')
      .attr('pointer-events', zoomed ? null : 'none')
      .style('cursor', zoomed ? 'pointer' : null)
      .style('display', zoomed || hovering ? null : 'none');
    var rect = badge.append('rect').attr('rx', 9).attr('ry', 9);
    var text = badge.append('text')
      .attr('text-anchor', left ? 'start' : 'end')
      .attr('dominant-baseline', 'central')
      .attr('font-size', '11px')
      .attr('font-family', "'DM Sans', system-ui, sans-serif")
      .attr('fill', zoomed ? colors.text : colors.hint)
      .text(zoomed ? '↺ Reset zoom' : 'Drag to zoom');

    var w = text.node().getComputedTextLength() || text.text().length * 6.5;
    var h = 18;
    text.attr('x', left ? 8 : -8).attr('y', h / 2);
    if (zoomed) {
      rect.attr('x', left ? 0 : -w - 16).attr('y', 0).attr('width', w + 16).attr('height', h)
        .attr('fill', colors.fill).attr('stroke', colors.stroke);
    } else {
      rect.remove();
    }
  }

  function attachX(layer, opts) {
    var d3 = global.d3;
    var brushing = false;
    var hovering = false;
    var zoomed = !!opts.zoomed;
    var layerNode = layer.node();
    guard(layerNode.ownerSVGElement);
    // A panel that keeps its SVG across zooms hands a getter: the scale the
    // traces are drawn with changes under the brush.
    var currentX = function () { return opts.getXScale ? opts.getXScale() : opts.xScale; };

    var brush = d3.brushX()
      .extent([[0, 0], [opts.width, opts.height]])
      .on('start', function () {
        brushing = true;
        if (opts.onLeave) opts.onLeave();
      })
      .on('end', function (event) {
        brushing = false;
        // Clearing the selection below re-enters here with no selection and no
        // sourceEvent; a real press-and-release that drew nothing has both.
        if (!event.selection) {
          if (opts.onClick && event.sourceEvent) {
            // A touchend carries no clientX: d3.pointer gives NaN there -- not a click position.
            var mx = d3.pointer(event.sourceEvent, overlayNode)[0];
            if (isFinite(mx)) opts.onClick(event.sourceEvent, mx);
          }
          return;
        }
        var s = event.selection;
        layer.call(brush.move, null);
        if (s[1] - s[0] < MIN_BRUSH_PX) {
          // A slip of the hand while clicking is still a click.
          if (opts.onClick && event.sourceEvent) opts.onClick(event.sourceEvent, (s[0] + s[1]) / 2);
          return;
        }
        var x = currentX();
        var d0 = x.invert(s[0]);
        var d1 = x.invert(s[1]);
        // Pixel order, left to right: descending on a reversed axis (MW).
        if (d0 !== d1) opts.onZoom([d0, d1]);
      });

    layer.call(brush);
    layer.select('.selection')
      .attr('fill', 'rgba(59, 130, 246, 0.15)')
      .attr('stroke', 'rgba(59, 130, 246, 0.4)');
    var overlay = layer.select('.overlay')
      .attr('fill', 'none')
      .attr('pointer-events', 'all')
      .style('cursor', 'crosshair');

    // Drawn in the brush layer's PARENT, after it: d3's brush listens on its whole
    // group and reads event.target.__data__.type, which a badge inside it lacks.
    var badge = d3.select(layerNode.parentNode).append('g').attr('class', 'ga-zoom-badge')
      .on('click', function () { if (zoomed) opts.onReset(); });
    renderBadge(badge, opts, zoomed, hovering);

    var overlayNode = overlay.node();
    overlayNode.addEventListener('mouseenter', function () {
      hovering = true;
      if (!zoomed) badge.style('display', null);
    });
    overlayNode.addEventListener('mousemove', function (event) {
      if (brushing || !opts.onHover) return;
      opts.onHover(event, d3.pointer(event, overlayNode)[0]);
    });
    overlayNode.addEventListener('mouseleave', function () {
      hovering = false;
      if (!zoomed) badge.style('display', 'none');
      if (opts.onLeave) opts.onLeave();
    });
    overlayNode.addEventListener('dblclick', function () {
      if (zoomed) opts.onReset();
    });
    // No disposer: the overlay and the badge live inside the panel's SVG and go
    // with it.

    return {
      brush: brush,
      overlay: overlayNode,
      badge: badge.node(),
      setZoomed: function (z) {
        zoomed = !!z;
        renderBadge(badge, opts, zoomed, hovering);
      },
    };
  }

  global.GelAnalyzer.Viz.BrushZoom = {
    attachX: attachX,
    fitY: fitY,
    guard: guard,
  };
})(window);
