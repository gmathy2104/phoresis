/* Guided tours -- the runner (spec docs/superpowers/specs/2026-10-22-guided-tours-design.md §3.5).
 *
 * Reads the island the launcher wrote (#gt-tour-data: the tour, this user's seen version, the endpoints, the CSRF
 * token), then:
 *  - keeps the REACHABLE steps: the element is there and visible, or hidden only because the tab panel it sits in
 *    ([data-pp-panel]) is closed -- the runner opens that panel's [data-pp-tab], on Next AND on Back; a step with
 *    wait_ms is kept before its element exists (Driver waits, then skips it);
 *  - on a first visit (auto_start, unseen version, enough steps, no <dialog> open) shows a welcome card whose four
 *    exits -- Start, Not now, x, Esc -- all count;
 *  - drives Driver.js with a key guard (capture phase on window) so the page's own shortcuts stay quiet;
 *  - records the end (completed / dismissed) and the events, fire-and-forget: the tour never waits on the network.
 * Driver 1.10.2's own facts it relies on: keyboard read on window in the bubble phase, destroy() reporting "api",
 * movePrevious() on the first step ending the tour, onDestroyed skipped for a tour closed during a wait on its first
 * step (guided_tours/README.md). */
(function () {
  'use strict';

  var island = document.getElementById('gt-tour-data');
  if (!island || !window.driver || !window.driver.js || typeof window.driver.js.driver !== 'function') return;
  var DATA;
  try { DATA = JSON.parse(island.textContent); } catch (err) { return; }
  var TOUR = DATA && DATA.tour;
  if (!TOUR || !TOUR.steps || !TOUR.steps.length) return;
  var make = window.driver.js.driver;

  // ---- the server: fire-and-forget, only {"ok": true} counts as saved ----
  function post(url, body) {
    var payload = { tour_id: TOUR.tour_id, version: TOUR.version };
    Object.keys(body).forEach(function (key) { payload[key] = body[key]; });
    return fetch(url, {
      method: 'POST',
      keepalive: true,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': DATA.csrf || '' },
      body: JSON.stringify(payload),
    });
  }
  function record(event, extra) {
    var body = { event: event };
    if (extra) Object.keys(extra).forEach(function (key) { body[key] = extra[key]; });
    post(DATA.urls.events, body).catch(function () { /* an event lost is not worth a word */ });
  }
  function saveProgress(status) {
    DATA.seen_version = TOUR.version; // not offered again on this page view, whatever the network says
    post(DATA.urls.progress, { status: status })
      .then(function (response) {
        var type = response.headers.get('Content-Type') || '';
        return response.ok && type.indexOf('application/json') === 0 ? response.json() : null;
      })
      .then(function (body) {
        if (!body || !body.ok) console.warn('guided tour: the end of ' + TOUR.tour_id + ' was not saved');
      })
      .catch(function (err) { console.warn('guided tour: the end of ' + TOUR.tour_id + ' was not saved', err); });
  }

  // ---- the steps ----
  function target(key) { return document.querySelector('[data-tour="' + key + '"]'); }
  function tabOf(panel) {
    var name = panel && panel.getAttribute('data-pp-panel');
    return name ? document.querySelector('[data-pp-tab="' + name + '"]') : null;
  }
  function hiddenBetween(el, stop) {
    for (var node = el; node && node !== stop; node = node.parentElement) {
      if (node.hidden || getComputedStyle(node).display === 'none') return true;
    }
    return false;
  }
  function reachable(step) {
    var el = target(step.key);
    if (!el) return !!step.wait_ms;
    if (el.getClientRects().length) return true;
    var panel = el.closest('[data-pp-panel]');
    return !!panel && !!tabOf(panel) && !hiddenBetween(el, panel);
  }
  // Idempotent: Driver calls a step's element function again on every DOM change during a wait.
  function openPanelOf(el) {
    var tab = el ? tabOf(el.closest('[data-pp-panel]')) : null;
    if (tab && tab.getAttribute('aria-selected') !== 'true') tab.click();
  }
  function selectedTab() { return document.querySelector('[data-pp-tab][aria-selected="true"]'); }

  function escapeAttr(value) { return String(value).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;'); }
  function description(step) {
    if (!step.more || !DATA.guide_url) return step.text;
    var href = DATA.guide_url + '#' + encodeURIComponent(step.more);
    return step.text + '<br><a class="gt-more" href="' + escapeAttr(href) + '" target="_blank" rel="noopener">' +
      'More in the guide <i class="bi bi-box-arrow-up-right" aria-hidden="true"></i></a>';
  }

  // ---- what is running: the welcome card or the tour ----
  var current = null; // { kind: 'card' | 'tour', drv, reason }

  function keysHint(popover) {
    var hint = document.createElement('span');
    hint.className = 'gt-keys';
    hint.innerHTML = '<kbd>←</kbd> <kbd>→</kbd> · <kbd>Esc</kbd>';
    popover.footer.insertBefore(hint, popover.footer.firstChild);
  }

  // Driver skips onDestroyed in one case (a tour closed during a wait on its first step): whatever ended it, the
  // runner's state follows Driver's.
  function settle(run) {
    setTimeout(function () {
      if (current === run && !run.drv.isActive()) run.onEnd(null, null);
    }, 0);
  }

  function start(trigger) {
    if (current) return;
    var kept = TOUR.steps.filter(reachable);
    if (!kept.length) return;
    var leftOut = TOUR.steps.filter(function (step) { return kept.indexOf(step) < 0; }).map(function (s) { return s.key; });
    if (document.activeElement && document.activeElement !== document.body && document.activeElement.blur) {
      document.activeElement.blur(); // typing must not go into a page field while the tour runs
    }
    var homeTab = selectedTab();
    var run = { kind: 'tour', reason: null, ended: false, index: null };
    run.onEnd = function (step, opts) {
      if (run.ended) return;
      run.ended = true;
      var why = run.reason || (opts && opts.reason) || 'close';
      var index = step && step.data ? step.data.index : run.index;
      if (why === 'done') {
        record('completed');
        saveProgress('completed');
      } else {
        record('dismissed', { step_index: index, detail: { reason: why } });
        saveProgress('dismissed');
      }
      if (homeTab && homeTab.getAttribute('aria-selected') !== 'true') homeTab.click();
      if (current === run) current = null;
    };
    run.drv = make({
      popoverClass: 'gt-popover',
      overlayColor: 'var(--gt-overlay)', // an inline fill takes a variable: a theme switch during the tour follows
      overlayOpacity: 1,
      stagePadding: 6,
      stageRadius: 8,
      smoothScroll: true,
      showProgress: true,
      progressText: '{{current}} / {{total}}',
      nextBtnText: 'Next',
      prevBtnText: 'Back',
      doneBtnText: 'Done',
      allowKeyboardControl: false, // the guard below drives ← → Esc
      disableActiveInteraction: true,
      onPopoverRender: keysHint,
      steps: kept.map(function (step) {
        var driveStep = {
          element: function () { var el = target(step.key); openPanelOf(el); return el; },
          popover: {
            title: step.title,
            description: description(step),
            side: step.side || undefined,
            align: step.align || undefined,
          },
          data: { key: step.key, index: TOUR.steps.indexOf(step) },
        };
        if (step.wait_ms) {
          driveStep.waitForElement = step.wait_ms;
          driveStep.skipMissingElement = true;
        }
        return driveStep;
      }),
      // onHighlightStarted, not onHighlighted: Driver calls the latter at the end of its animation, from a
      // requestAnimationFrame loop that a background tab never runs -- the step would go unrecorded.
      onHighlightStarted: function (el, step) {
        run.index = step.data.index;
        record('step', { step_key: step.data.key, step_index: step.data.index });
      },
      onDestroyed: function (el, step, opts) { run.onEnd(step, opts); },
    });
    current = run;
    record('started', { detail: { trigger: trigger, left_out: leftOut } });
    run.drv.drive();
  }

  function offer() {
    if (current || !TOUR.auto_start || !TOUR.welcome) return;
    if (DATA.seen_version !== null && DATA.seen_version >= TOUR.version) return;
    if (TOUR.steps.filter(reachable).length < Math.min(3, TOUR.steps.length)) return;
    if (document.querySelector('dialog[open], [data-gt-hold]')) return; // a modal that is no <dialog> carries the mark while it is open
    var run = { kind: 'card', reason: null, ended: false, startNext: false };
    run.onEnd = function () {
      if (run.ended) return;
      run.ended = true;
      if (current === run) current = null;
      if (run.startNext) { start('first_visit'); return; }
      record('declined', { detail: { reason: run.reason || 'close' } });
      saveProgress('dismissed');
    };
    run.drv = make({
      popoverClass: 'gt-popover gt-welcome',
      overlayColor: 'var(--gt-overlay)',
      overlayOpacity: 1,
      allowKeyboardControl: false,
      steps: [{
        popover: {
          title: TOUR.welcome.title,
          description: TOUR.welcome.text,
          showButtons: ['next', 'close'],
          nextBtnText: 'Start the tour',
          onNextClick: function () { run.startNext = true; run.drv.destroy(); settle(run); },
          onPopoverRender: function (popover) {
            var later = document.createElement('button');
            later.type = 'button';
            later.className = 'driver-popover-footer-btn gt-later';
            later.textContent = 'Not now';
            later.addEventListener('click', function () { run.reason = 'not_now'; run.drv.destroy(); settle(run); });
            popover.footerButtons.insertBefore(later, popover.footerButtons.firstChild);
          },
        },
      }],
      onDestroyed: function () { run.onEnd(); },
    });
    current = run;
    record('offered');
    run.drv.drive();
  }

  function finish(run, why) {
    run.reason = why;
    run.drv.destroy();
    settle(run);
  }

  // ---- the key guard: while something runs, ← → Esc are ours and nothing reaches the page ----
  function guard(e) {
    var run = current;
    if (!run || !run.drv.isActive()) return;
    if (e.key === 'Tab') return; // Driver keeps the focus in the popover
    var inPopover = !!(e.target && e.target.closest && e.target.closest('.driver-popover'));
    var onControl = inPopover && /^(BUTTON|A)$/.test(e.target.tagName);
    if ((e.key === 'Enter' || e.key === ' ') && onControl) return; // a popover button or link does its job
    e.stopImmediatePropagation();
    if (e.type !== 'keydown') { if (!inPopover) e.preventDefault(); return; }
    if (e.key === 'Escape') { e.preventDefault(); finish(run, 'escape'); return; }
    if (run.kind === 'tour' && e.key === 'ArrowRight') {
      e.preventDefault();
      if (run.drv.isLastStep()) finish(run, 'done'); else run.drv.moveNext();
      return;
    }
    if (run.kind === 'tour' && e.key === 'ArrowLeft') {
      e.preventDefault();
      if (run.drv.hasPreviousStep()) run.drv.movePrevious(); // on the first step Driver would end the tour
      return;
    }
    if (!inPopover || e.key === 'Enter' || e.key === ' ') e.preventDefault(); // no typing, no submit, no scroll
  }
  window.addEventListener('keydown', guard, true);
  window.addEventListener('keyup', guard, true);

  // A click on the overlay or a popover button may end the run inside Driver. Its reason is read HERE, before
  // Driver acts: Driver calls onDestroyed only once a step's animation has finished (a requestAnimationFrame loop),
  // so a quick click -- or a background tab -- ends the run through settle(), which must know why.
  document.addEventListener('click', function (e) {
    var run = current;
    if (!run || !e.target.closest) return;
    if (e.target.closest('.driver-popover-close-btn')) run.reason = run.reason || 'close';
    else if (e.target.closest('.driver-overlay')) run.reason = run.reason || 'overlay';
    else if (run.kind === 'tour' && e.target.closest('.driver-popover-next-btn') && run.drv.isLastStep()) {
      run.reason = 'done';
    }
    if (e.target.closest('.driver-overlay, .driver-popover')) settle(run);
  }, true);

  document.addEventListener('click', function (e) {
    if (e.target.closest && e.target.closest('[data-gt-launch]')) { e.preventDefault(); start('button'); }
  });

  // the first-visit offer waits for the page to settle (charts, panels, a dialog a hash opens)
  function whenLoaded(fn) {
    if (document.readyState === 'complete') setTimeout(fn, 300);
    else window.addEventListener('load', function () { setTimeout(fn, 300); });
  }

  // A link may ask for this page's tour (Discover on the home, /tours/): ?tour=<tour_id> starts it instead of the
  // welcome card, once, and leaves the address clean. Another page's id, or a stale one, does nothing.
  function fromLink() {
    var params = new URLSearchParams(window.location.search);
    if (params.get('tour') !== TOUR.tour_id) return false;
    params.delete('tour');
    var query = params.toString();
    history.replaceState(history.state, '', window.location.pathname + (query ? '?' + query : '') + window.location.hash);
    start('link');
    return true;
  }
  whenLoaded(function () { if (!fromLink()) offer(); });
})();
