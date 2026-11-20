/**
 * GelAnalyzer.Viz.Panel — base class formalizing the panel contract.
 *
 * Lifecycle (creator-invoked): const p = new Panel(opts); p.init();
 * NEVER call init() from the constructor — subclass class-fields initialize
 * AFTER super(), so they would be undefined inside a ctor-called init().
 *
 * Teardown is guaranteed by construction: use the _on/_onWindow/_observe/_raf/
 * _d3zoom/_d3interrupt helpers and destroy() undoes everything.
 */
(function (global) {
  'use strict';

  global.GelAnalyzer = global.GelAnalyzer || {};
  global.GelAnalyzer.Viz = global.GelAnalyzer.Viz || {};

  class Panel {
    constructor({ container, eventBus, state, options, tooltipLayer }) {
      this.container = container;
      this.eventBus = eventBus;
      this.state = state;
      this.options = options || {};
      this.tooltipLayer = tooltipLayer || null;
      this._disposers = [];
    }

    init() {}      // override: build DOM, subscribe, first render
    render() {}    // override: idempotent (re)draw

    destroy() {
      this._disposers.forEach((fn) => {
        try { fn(); } catch (e) { console.warn('[GelAnalyzer.Viz.Panel] disposer threw during teardown:', e); }
      });
      this._disposers = [];
    }

    _on(evt, handler) {
      this.eventBus.on(evt, handler);
      this._disposers.push(() => this.eventBus.off(evt, handler));
    }
    _onWindow(type, handler) {
      window.addEventListener(type, handler);
      this._disposers.push(() => window.removeEventListener(type, handler));
    }
    _observe(el, cb) {
      if (!el) return;
      const ro = new ResizeObserver(cb);
      ro.observe(el);
      this._disposers.push(() => ro.disconnect());
    }
    /**
     * One-shot deferred work. Each call registers its own cancel disposer, so do
     * NOT call this inside a per-render/debounce loop — for cancel-previous-then-
     * reschedule patterns (e.g. resize coalescing) keep a local id and manage
     * cancelAnimationFrame yourself (register one teardown disposer if needed).
     */
    _raf(fn) {
      const id = requestAnimationFrame(fn);
      this._disposers.push(() => cancelAnimationFrame(id));
      return id;
    }
    _d3zoom(selection) {
      this._disposers.push(() => selection.on('.zoom', null).on('.brush', null));
    }
    _d3interrupt(selection) {
      this._disposers.push(() => selection.interrupt());
    }
    /**
     * _chartArea(container) — reserve legend space so a flow legend never crops.
     * Makes `container` a flex column and returns a flex:1 chart-area child to
     * draw the <svg> into (size the svg from THIS element's rect, not the
     * container's). Append the legend to `container` AFTER drawing it so it is a
     * flex-shrink:0 sibling that keeps its natural height. Idempotent.
     * IMPORTANT: populate the legend BEFORE reading the chart-area's rect, so the
     * chart-area's flex:1 has already yielded (container height − legend height).
     */
    _chartArea(container) {
      if (!container) return null;
      container.style.display = 'flex';
      container.style.flexDirection = 'column';
      let area = container.querySelector(':scope > .ga-chart-area');
      if (!area) {
        area = document.createElement('div');
        area.className = 'ga-chart-area';
        area.style.cssText = 'flex:1 1 auto;min-height:0;position:relative;';
        container.insertBefore(area, container.firstChild);
      }
      return area;
    }
  }

  global.GelAnalyzer.Viz.Panel = Panel;
})(window);
