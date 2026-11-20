/**
 * GelAnalyzer.Viz.mount(containerEl, { panelDefs, eventBus, state, options })
 *
 * Builds the .ga-viz-root skeleton inside containerEl, instantiates each panel
 * into its own sub-container, and returns a lifecycle handle the HOST owns.
 *
 * panelDefs: [{ name, PanelClass, containerClass, markup }]
 *   - markup (optional): HTML string written into the sub-container BEFORE the
 *     panel is constructed, so the panel's init() can drill into expected DOM
 *     (e.g. .dm-panel-header / .dm-panel-content) it does not build itself.
 * Returns: { destroy, getPanel, getState, on, _eventBus, _panels }
 */
(function (global) {
  'use strict';

  global.GelAnalyzer = global.GelAnalyzer || {};
  global.GelAnalyzer.Viz = global.GelAnalyzer.Viz || {};

  function mount(containerEl, { panelDefs, eventBus, state, options } = {}) {
    if (!containerEl || !containerEl.dataset) {
      throw new Error('[GelAnalyzer.Viz] containerEl must be a DOM element.');
    }
    if (!global.d3) {
      throw new Error('[GelAnalyzer.Viz] d3 must be loaded before mounting.');
    }
    if (containerEl.dataset.gaVizMounted) {
      throw new Error('[GelAnalyzer.Viz] container already has a mounted Viz component.');
    }
    containerEl.dataset.gaVizMounted = '1';

    const ownsEventBus = !eventBus;
    eventBus = eventBus || new global.GelAnalyzer.Core.EventBus();

    const root = document.createElement('div');
    root.className = 'ga-viz-root';

    const tooltipLayer = document.createElement('div');
    tooltipLayer.className = 'ga-viz-tooltip-layer';
    root.appendChild(tooltipLayer);

    const panels = {};
    try {
      (panelDefs || []).forEach((def) => {
        const panelEl = document.createElement('div');
        if (def.containerClass) panelEl.className = def.containerClass;
        panelEl.dataset.gaPanel = def.name;
        if (def.markup) panelEl.innerHTML = def.markup;
        root.appendChild(panelEl);

        const panel = new def.PanelClass({
          container: panelEl,
          eventBus,
          state,
          options,
          tooltipLayer,
        });
        panel.init();
        panels[def.name] = panel;
      });
      containerEl.appendChild(root);
    } catch (e) {
      // Transactional mount: undo the partial skeleton + sentinel on failure
      Object.values(panels).forEach((p) => { try { p.destroy(); } catch (_) { /* ignore */ } });
      root.remove();
      delete containerEl.dataset.gaVizMounted;
      throw e;
    }

    const capturedBus = eventBus;
    return {
      destroy() {
        Object.values(panels).forEach((p) => {
          try { p.destroy(); } catch (e) { console.warn('[GelAnalyzer.Viz.mount] panel destroy threw:', e); }
        });
        root.remove();
        delete containerEl.dataset.gaVizMounted;
        if (ownsEventBus && capturedBus.clear) capturedBus.clear();
      },
      getPanel: (name) => panels[name],
      getState: () => state,
      on: (evt, cb) => capturedBus.on(evt, cb),
      _eventBus: capturedBus,
      _panels: panels,
    };
  }

  global.GelAnalyzer.Viz.mount = mount;

  // A body-level, viewport-fixed overlay for tooltips that must ESCAPE a clipped host (e.g. a
  // Gridstack tile with overflow:hidden). Carries .ga-viz-root so scoped tooltip styles apply; the
  // inline position beats the .ga-viz-root all:initial reset. Singleton, shared by every panel that
  // opts in via options.tooltipToBody (only one tooltip is visible at a time anyway).
  global.GelAnalyzer.Viz.tooltipPortal = function () {
    var p = document.getElementById('ga-viz-tip-portal');
    if (!p) {
      p = document.createElement('div');
      p.id = 'ga-viz-tip-portal';
      p.className = 'ga-viz-root';
      p.style.cssText = 'position:fixed;left:0;top:0;width:0;height:0;overflow:visible;pointer-events:none;z-index:2147483000';
      document.body.appendChild(p);
    }
    return p;
  };
})(window);
