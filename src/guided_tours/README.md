# `guided_tours` — a visual companion on each page

A short, skippable tour that points at the parts of a page: a spotlight on the element, a popover beside it,
← → Esc. CSS prefix `.gt-`.

Ported from ds-hub-django (`guided_tours/`, at its commit `e37dc02`). Kept as is: `tour_schema.py`, the models and
their migration, the two endpoints and the runner `static/guided_tours/js/gt-tours.js` (byte-identical, so a later
resync is a file copy). Adapted: the launcher (the hub hangs it on its guide's `?` button, Phoresis on its two page
chromes), the colour tokens, the `/tours/` page, and the tours themselves, rewritten for the pages Phoresis has.
Left out: the hub's per-app access gate, its home "Discover" widget and the links to its user guides.

Depends on `phoresis_core` only. `phoresis_ui`'s top bar and `gel_analyzer`'s workbench header call its template
tag; nothing else imports it.

How a page gets its tour: the page chrome calls `{% gt_launcher %}` — `components/_topbar.html` on the application
pages, `gel_analyzer/workbench/_identity.html` and the headers of the comparison and of the gel dashboard on the
workbench pages (`{% gt_launcher "workbench" %}`). The tag looks the page up by `context.template_name`, the template
the view rendered. A page whose template a tour names gets the **Tour** compass, Driver.js, the runner and a JSON
island; every other page gets nothing.

## Adding a tour to a page

1. **Write `<app>/tours/<tour_id>.json`** in the app that owns the page (`gel_analyzer/tours/ga.image-list.json` is
   an example):

   ```json
   {
     "tour_id": "ga.image-list",
     "version": 1,
     "entry": "gel_analyzer:image_list",
     "templates": ["gel_analyzer/images/list.html"],
     "auto_start": true,
     "welcome": {"title": "A tour of the gel images", "text": "..."},
     "steps": [
       {"key": "il-filters", "title": "Find an image", "text": "...", "side": "bottom", "align": "start"}
     ]
   }
   ```

   - `tour_id` = the file name; never reused for another page. `templates` = the PAGE templates (the ones the view
     renders), one tour per template.
   - 1 to 8 steps. `title` ≤ 60 characters, `text` ≤ 280, English like the interface. Markup: `<b>`, `<i>`, `<kbd>`,
     `<code>`, `<br>`, without attributes — Driver writes them as HTML.
   - `side` (`top`, `right`, `bottom`, `left`), `align` (`start`, `center`, `end`): optional placement.
   - `wait_ms` (≤ 3000): an element drawn after load (a chart).
   - `auto_start: true` shows a welcome card (Start the tour / Not now) on a person's first visit of each version;
     its text names no step count — a reader may see fewer steps. `false` (the default): the compass only.
     The card is offered only when **at least three steps** (or all of them, in a shorter tour) are on the page, and
     it waits while a `<dialog>` is open, or an element carrying `data-gt-hold`.
   - `entry` (optional): the URL name, without arguments, of a page where the tour can be taken
     (`"gel_analyzer:image_list"`). With it the tour gets a **Start** link on `/tours/`; the link is the page's
     address plus `?tour=<tour_id>`, which makes the runner start the tour on arrival, then drops the parameter.
     A tour of a record page (an image, an analysis) has none and is listed without a link.
   - `guide` and a step's `more` link a step to a user-guide section. The schema keeps them; Phoresis serves no
     guide pages, so no tour uses them (`gt_tags._guide_url`).

2. **Tag the elements** with `data-tour="<key>"` in the templates (or the partials they include). Never aim at a
   class or an id: a redesign must not move a tour silently. An element that is not on the page (no warning to show,
   an empty list) is simply left out of the tour — tag the first row of a list with `{% if forloop.first %}`.
   A `{% btn %}` renders its own element: wrap it in a `<span data-tour="...">`.

3. **Run the tests**: `python -m pytest src/guided_tours`. `tests/test_tour_files.py` refuses a file that breaks a
   rule, a missing template, a key found in no template, a `data-tour` no tour names, an entry that does not reverse.

4. **Restart `runserver`**: tours are read once at start-up (`GuidedToursConfig.ready`); the dev autoreloader does
   not watch `.json`.

**Bump `version`** when a change deserves to be seen again (new or reordered steps, a rewritten explanation): every
user is then offered the tour once more. A typo fix does not bump it.

## The look

`static/guided_tours/css/gt-tours.css` dresses Driver's popover with `--gt-*` tokens on `:root`, each falling back
from the workbench's `--ga-wb-*` to the application pages' `--color-*`. Both families switch on the `<html>`
`data-theme` attribute, so night / day follows the page's own switch.

## What is recorded

- `TourProgress` (one row per user and tour): the version last seen and `completed` / `dismissed`. A newer version
  replaces the row; within a version `completed` wins.
- `TourEvent`: `offered`, `declined`, `started` (`detail.trigger`, `detail.left_out` — the keys that were not on the
  page), `step`, `completed`, `dismissed` (`detail.reason`: `escape`, `close`, `overlay`…).
- Both are listed read-only in the admin.
- Endpoints `POST /tours/api/progress/` and `/tours/api/events/` answer JSON (`401` when the session is gone, never a
  login redirect).

## Driver.js, vendored

`static/guided_tours/vendor/driverjs/1.10.2/` — `driver.js.iife.js`, `driver.css`, `LICENSE` (MIT), copied from
ds-hub-django's vendored copy, itself from `https://registry.npmjs.org/driver.js/-/driver.js-1.10.2.tgz`, npm
integrity `sha512-L/EMTriJPAmg+5kIFmrjzt3TI+1NblhHOV/UZkfpgU/uxhSflGheynMBxk5oImDSy6seAEkIl6MzNOc0zdoKtg==`
(the checksum is the tarball's; an end-of-file hook added a final newline to `driver.js.iife.js` and `LICENSE`).
Never a CDN (AGENTS.md §1).

What the runner relies on in 1.10.2: the keyboard is read on `window` in the bubble phase (the runner's guard, in the
capture phase, drives ← → Esc itself and stops every other key so the page's shortcuts stay quiet); `destroy()`
reports the reason `api`; `movePrevious()` on the first step ends the tour; `onHighlighted` and `onDestroyed` run
only once a step's animation has finished, so the runner records a step on `onHighlightStarted` and settles its own
state when Driver is no longer active.

**Upgrading**: a new folder `vendor/driverjs/<version>/`, `_launcher.html` pointed at it, then browser-verify the
keyboard (in and out of a page field), the welcome card's four exits, night and day, before the old folder goes.
