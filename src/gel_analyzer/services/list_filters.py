"""
Query-string helpers for the filter bar of the gel list pages.

A list page's filters are ONE GET form: each filter is a <select multiple> (a
pp-picker pill), an input of that form, so a filter lives in the URL as a repeated parameter
(``?project=12&project=none``). These helpers read those parameters, turn them into
a filter, shape one filter for ``gel_analyzer/partials/_filter_picker.html`` and build
the URL behind an active-filter chip. Pure functions over a ``QueryDict``: no query,
no request.

Used by the image list (``views/images.py``) and the analyses list (``views/analyses.py``).
"""

from django.db.models import Q

# The value of the "No project" / "No assay" option of a pill.
NONE_VALUE = "none"

# Postgres bigint holds 19 digits; 18 keeps every accepted id inside it.
_MAX_ID_DIGITS = 18


def int_values(query_dict, param):
    """
    The valid ids among ``query_dict.getlist(param)``, and whether ``none`` is among them.

    Returns ``(ints, has_none)``: ``ints`` keeps URL order without duplicates; anything
    that is not a plain ASCII number of at most 18 digits is ignored (``"²".isdigit()``
    is True and ``int("²")`` raises; a 20-digit id would overflow a bigint).
    """
    ints, has_none = [], False
    for raw in query_dict.getlist(param):
        if raw == NONE_VALUE:
            has_none = True
        elif raw.isascii() and raw.isdigit() and len(raw) <= _MAX_ID_DIGITS:
            value = int(raw)
            if value not in ints:
                ints.append(value)
    return ints, has_none


def ids_q(field, ids, has_none=False):
    """``field`` among ``ids``, or null when the "none" option is ticked; ``Q()`` (no filter) when neither."""
    q = Q()
    if ids:
        q |= Q(**{f"{field}__in": ids})
    if has_none:
        q |= Q(**{f"{field}__isnull": True})
    return q


def selected_values(ids, has_none=False):
    """The ticked values of a pill, as the strings its checkboxes carry (``int_values`` read back)."""
    return [str(i) for i in ids] + ([NONE_VALUE] if has_none else [])


def choice_values(query_dict, param, allowed):
    """The values of ``param`` that are in ``allowed``, in URL order, without duplicates."""
    allowed = set(allowed)
    values = []
    for raw in query_dict.getlist(param):
        if raw in allowed and raw not in values:
            values.append(raw)
    return values


def remove_value_url(query_dict, param, value):
    """
    ``"?" + querystring`` of the current page minus ONE value of ``param``, and minus ``page``.

    Django's ``{% querystring %}`` can only replace or drop a whole parameter, not one
    value of a repeated one. ``page`` goes because a changed filter starts at page 1.
    """
    params = query_dict.copy()
    remaining = [v for v in params.getlist(param) if v != str(value)]
    if remaining:
        params.setlist(param, remaining)
    else:
        params.pop(param, None)
    params.pop("page", None)
    return "?" + params.urlencode()


def facet(param, label, options, selected):
    """
    One pill of the bar, as ``_filter_picker.html`` renders it.

    ``options`` are ``(value, label, count)`` triples in display order; ``selected``
    the values ticked in the URL. A ticked value no option carries (an id with no
    image, a hand-edited URL) gets a row of its own with a count of 0: its checkbox is
    a form input, and a value without one would vanish at the next submit while the
    page in front of the user is still filtered on it.
    """
    selected = list(dict.fromkeys(str(v) for v in selected))
    rows = [
        {"value": str(value), "label": option_label, "count": count, "checked": str(value) in selected}
        for value, option_label, count in options
    ]
    known = {row["value"] for row in rows}
    rows += [{"value": v, "label": f"#{v}", "count": 0, "checked": True} for v in selected if v not in known]
    checked = [row for row in rows if row["checked"]]
    return {
        "param": param,
        "label": label,
        "options": rows,
        "checked": checked,
        "selected_count": len(checked),
        # Closed pill: "all · <n>" when nothing is ticked, else the first ticked label
        # and a "+N" badge for the rest.
        "summary": checked[0]["label"] if checked else f"all · {len(rows)}",
        "extra": max(len(checked) - 1, 0),
    }


def facet_chips(query_dict, facets):
    """One removable chip per ticked value of each facet: ``{"label", "url"}``."""
    return [
        {
            "label": f"{f['label']}: {row['label']}",
            "url": remove_value_url(query_dict, f["param"], row["value"]),
        }
        for f in facets
        for row in f["checked"]
    ]
