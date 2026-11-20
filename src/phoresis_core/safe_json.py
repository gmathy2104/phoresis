"""JSON for a ``<script>`` element, without letting a stored string close it.

``json.dumps`` escapes quotes and backslashes but not ``<``, ``>`` or ``&``. Inside a
``<script>`` element the HTML tokenizer runs BEFORE JavaScript and ends the element at
the first ``</script`` it meets -- inside a JSON string included, and whatever the
``type=`` -- so a sample, file or design name containing
``</script><img src=x onerror=alert(1)>`` ends the block and the rest runs as HTML.
``{{ x_json|safe }}`` and ``mark_safe(json.dumps(x))`` in a script were a stored XSS on
32 sites on 2026-09-27; ``tools/lint/check_unsafe_json_in_templates.py`` keeps the class
closed.

The escaping is the one Django's ``json_script`` applies: ``<``, ``>`` and ``&`` become
``\\u003C``, ``\\u003E`` and ``\\u0026``. Those escapes are legal in a JSON string and in
a JS string literal and decode to the very same characters, so the value the page's JS
receives is unchanged.

Why not ``json_script`` itself: it serializes with ``DjangoJSONEncoder`` and pairs with
``JSON.parse``. Views here dump with their own ``default=`` / ``cls=``, and payloads
carry ``NaN`` -- a legal JS literal, a ``JSON.parse`` error. These helpers keep each
view's exact ``json.dumps`` call and add only the escaping, whether the template emits
the JSON as a JS literal or inside a ``<script type="application/json">`` island.

SCRIPT CONTEXT ONLY. The output is not safe inside an HTML attribute, where a quote
still ends the value: there, pass the plain string and let autoescape do its job.
"""

import json

from django.utils.safestring import SafeString, mark_safe

_SCRIPT_ESCAPES = {ord("<"): "\\u003C", ord(">"): "\\u003E", ord("&"): "\\u0026"}


def script_json(value, **dumps_kwargs) -> SafeString:
    """``json.dumps(value, **dumps_kwargs)``, safe to emit inside a ``<script>`` element."""
    return script_json_text(json.dumps(value, **dumps_kwargs))


def script_json_text(json_text: str) -> SafeString:
    """JSON that is ALREADY a string (``fig.to_json()``, a stored blob), made safe the same way."""
    return mark_safe(json_text.translate(_SCRIPT_ESCAPES))
