"""The rules a tour file obeys (spec docs/superpowers/specs/2026-10-22-guided-tours-design.md §3.2).

Pure Python, no Django import: the registry applies these rules at ``ready()`` and the preflight lint
``tools/lint/check_guided_tours.py`` applies the same ones to the files on disk, so the two can never disagree on
what a valid tour is. A file that breaks one rule is refused whole -- never a half-loaded tour.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_STEPS = 8
MAX_TITLE = 60
MAX_TEXT = 280
MAX_WAIT_MS = 3000
TOUR_ID = re.compile(r"^[a-z0-9.-]{3,64}$")
STEP_KEY = re.compile(r"^[a-z0-9-]{1,64}$")
SIDES = {"top", "right", "bottom", "left"}  # Driver's `Side` type (driver.js.d.ts)
ALIGNS = {"start", "center", "end"}
# Driver sets a popover's title and description with innerHTML: a few inline tags, and never an attribute
ALLOWED_TAGS = {"b", "i", "kbd", "code", "br"}
TAG = re.compile(r"<\s*(/?)\s*([a-zA-Z0-9]+)([^>]*)>")

TOP_FIELDS = {"tour_id", "version", "templates", "auto_start", "guide", "welcome", "steps", "entry"}
# "entry": a URL name without arguments where the tour can be taken from a link (Discover, /tours/); resolved at
# read time by guided_tours/discover.py, which skips and logs one that no longer reverses.
ENTRY = re.compile(r"^[a-z][a-z0-9_]*(?::[a-z][a-z0-9_]*)*:[A-Za-z0-9_-]+$")
GUIDE_FIELDS = {"app", "page"}
WELCOME_FIELDS = {"title", "text"}
STEP_FIELDS = {"key", "title", "text", "side", "align", "more", "wait_ms", "js"}


@dataclass(frozen=True)
class TourStep:
    key: str
    title: str
    text: str
    side: str = ""
    align: str = ""
    more: str = ""
    wait_ms: int = 0
    js: str = ""


@dataclass(frozen=True)
class Tour:
    tour_id: str
    version: int
    templates: tuple
    steps: tuple
    auto_start: bool = False
    entry: str = ""
    guide_app: str = ""
    guide_page: str = ""
    welcome_title: str = ""
    welcome_text: str = ""
    source: str = field(default="", compare=False)

    def as_client_dict(self):
        """What the page's runner receives (the JSON island): no server-only field."""
        return {
            "tour_id": self.tour_id,
            "version": self.version,
            "auto_start": self.auto_start,
            "welcome": {"title": self.welcome_title, "text": self.welcome_text} if self.auto_start else None,
            "steps": [
                {
                    "key": s.key,
                    "title": s.title,
                    "text": s.text,
                    "side": s.side or None,
                    "align": s.align or None,
                    "more": s.more or None,
                    "wait_ms": s.wait_ms or None,
                }
                for s in self.steps
            ],
        }


def _markup_errors(where, value):
    errors = []
    for match in TAG.finditer(value):
        closing, name, rest = match.group(1), match.group(2).lower(), match.group(3).strip()
        if name not in ALLOWED_TAGS:
            errors.append(f"{where}: tag <{closing}{name}> is not one of {', '.join(sorted(ALLOWED_TAGS))}")
        elif rest and rest != "/":
            errors.append(f"{where}: <{name}> carries an attribute ({rest[:30]}) -- none is allowed")
        elif rest == "/" and name != "br":
            errors.append(f"{where}: <{name}/> is not a self-closing tag")
    if "<" in TAG.sub("", value):
        errors.append(f"{where}: a stray '<' that is not an allowed tag")
    return errors


def _text(where, value, limit, errors, required=True):
    if value in (None, "") and not required:
        return
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{where}: a non-empty text is required")
        return
    if len(value) > limit:
        errors.append(f"{where}: {len(value)} characters, the limit is {limit}")
    errors.extend(_markup_errors(where, value))


def validate(data, filename):
    """Every rule broken by ``data`` (the parsed JSON of ``filename``), as sentences; empty = a valid tour."""
    errors = []
    if not isinstance(data, dict):
        return ["the file is not a JSON object"]
    unknown = set(data) - TOP_FIELDS
    if unknown:
        errors.append(f"unknown field(s): {', '.join(sorted(unknown))}")

    tour_id = data.get("tour_id")
    stem = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    stem = stem[:-5] if stem.endswith(".json") else stem
    if not isinstance(tour_id, str) or not TOUR_ID.match(tour_id):
        errors.append("tour_id: 3 to 64 characters among a-z, 0-9, '.' and '-'")
    elif tour_id != stem:
        errors.append(f"tour_id {tour_id!r} differs from the file name {stem!r}")

    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        errors.append("version: an integer, 1 or more")

    templates = data.get("templates")
    if (
        not isinstance(templates, list)
        or not templates
        or not all(isinstance(t, str) and t.endswith(".html") for t in templates)
    ):
        errors.append("templates: a non-empty list of page template names (*.html)")
    elif len(set(templates)) != len(templates):
        errors.append("templates: a template is listed twice")

    auto_start = data.get("auto_start", False)
    if not isinstance(auto_start, bool):
        errors.append("auto_start: true or false")

    entry = data.get("entry")
    if entry is not None and (not isinstance(entry, str) or not ENTRY.match(entry)):
        errors.append("entry: a URL name without arguments, 'namespace:name'")

    guide = data.get("guide")
    if guide is not None:
        if not isinstance(guide, dict) or set(guide) != GUIDE_FIELDS:
            errors.append("guide: an object with exactly 'app' and 'page'")
        elif not all(isinstance(guide[k], str) and guide[k] for k in GUIDE_FIELDS):
            errors.append("guide: 'app' and 'page' are non-empty texts")

    welcome = data.get("welcome")
    if welcome is not None:
        if not isinstance(welcome, dict) or set(welcome) - WELCOME_FIELDS:
            errors.append("welcome: an object with 'title' and 'text'")
        else:
            _text("welcome.title", welcome.get("title"), MAX_TITLE, errors)
            _text("welcome.text", welcome.get("text"), MAX_TEXT, errors)
    elif auto_start is True:
        errors.append("welcome: required when auto_start is true (the card the first visit shows)")

    steps = data.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        errors.append(f"steps: 1 to {MAX_STEPS} steps")
        return errors
    keys = []
    for index, step in enumerate(steps, start=1):
        where = f"step {index}"
        if not isinstance(step, dict):
            errors.append(f"{where}: not an object")
            continue
        unknown = set(step) - STEP_FIELDS
        if unknown:
            errors.append(f"{where}: unknown field(s): {', '.join(sorted(unknown))}")
        key = step.get("key")
        if not isinstance(key, str) or not STEP_KEY.match(key):
            errors.append(f"{where}: key: 1 to 64 characters among a-z, 0-9 and '-' (the data-tour value)")
        else:
            keys.append(key)
            where = f"step {index} ({key})"
        _text(f"{where} title", step.get("title"), MAX_TITLE, errors)
        _text(f"{where} text", step.get("text"), MAX_TEXT, errors)
        if step.get("side", "") not in SIDES | {""}:
            errors.append(f"{where}: side is one of {', '.join(sorted(SIDES))}")
        if step.get("align", "") not in ALIGNS | {""}:
            errors.append(f"{where}: align is one of {', '.join(sorted(ALIGNS))}")
        more = step.get("more")
        if more is not None:
            if not isinstance(more, str) or not more or more.startswith("#"):
                errors.append(f"{where}: more is a guide anchor, without '#'")
            elif guide is None:
                errors.append(f"{where}: more needs the tour's 'guide'")
        wait_ms = step.get("wait_ms")
        if wait_ms is not None and (
            not isinstance(wait_ms, int) or isinstance(wait_ms, bool) or not 1 <= wait_ms <= MAX_WAIT_MS
        ):
            errors.append(f"{where}: wait_ms is 1 to {MAX_WAIT_MS}")
        js = step.get("js")
        if js is not None and (not isinstance(js, str) or not js.endswith(".js")):
            errors.append(f"{where}: js is a static path ending in .js")
    if len(set(keys)) != len(keys):
        errors.append("steps: a key is used twice")
    return errors


def build(data, source=""):
    """The Tour of a file ``validate`` accepted."""
    guide = data.get("guide") or {}
    welcome = data.get("welcome") or {}
    return Tour(
        tour_id=data["tour_id"],
        version=data["version"],
        templates=tuple(data["templates"]),
        auto_start=data.get("auto_start", False),
        entry=data.get("entry", ""),
        guide_app=guide.get("app", ""),
        guide_page=guide.get("page", ""),
        welcome_title=welcome.get("title", ""),
        welcome_text=welcome.get("text", ""),
        steps=tuple(
            TourStep(
                key=s["key"],
                title=s["title"],
                text=s["text"],
                side=s.get("side", ""),
                align=s.get("align", ""),
                more=s.get("more", ""),
                wait_ms=s.get("wait_ms") or 0,
                js=s.get("js", ""),
            )
            for s in data["steps"]
        ),
        source=source,
    )


def iter_tour_files(app_dirs):
    """``(app_dir, path)`` of every tour file under the given app directories, in a stable order."""
    for app_dir in app_dirs:
        folder = Path(app_dir) / "tours"
        if folder.is_dir():
            for path in sorted(folder.glob("*.json")):
                yield Path(app_dir), path


def read_tours(app_dirs):
    """``(tours, refusals)`` for the given app directories: the valid tours, and ``(file, errors)`` for the others.

    Shared with the lint, so both refuse the same files for the same reasons: a duplicate ``tour_id`` or a template
    another tour already claims refuses the LATER file, named.
    """
    tours, refusals, claimed, ids = [], [], {}, {}
    for _app_dir, path in iter_tour_files(app_dirs):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            refusals.append((path, [f"not readable as JSON: {exc}"]))
            continue
        errors = validate(data, path.name)
        if not errors:
            if data["tour_id"] in ids:
                errors.append(f"tour_id {data['tour_id']!r} is already used by {ids[data['tour_id']].name}")
            for template in data["templates"]:
                if template in claimed:
                    errors.append(f"template {template} already carries the tour of {claimed[template].name}")
        if errors:
            refusals.append((path, errors))
            continue
        ids[data["tour_id"]] = path
        for template in data["templates"]:
            claimed[template] = path
        tours.append(build(data, source=str(path)))
    return tours, refusals
