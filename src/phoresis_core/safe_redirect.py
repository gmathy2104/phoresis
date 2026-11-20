"""
Safe redirect helpers — prevent open-redirect via untrusted `next` URLs.

Used to address CodeQL `py/url-redirection` findings across the project.
Wraps Django's `url_has_allowed_host_and_scheme` so call sites can stay
concise while still validating that a user-supplied URL targets our own
host.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme


def is_safe_next_url(request: HttpRequest, url: str | None) -> bool:
    """True if `url` is empty, relative, or points at the current host.

    Empty/None returns False (caller should fall back to a static target).
    Anything else must satisfy Django's standard open-redirect guard:
    same host, scheme-aware on HTTPS pages.
    """
    if not url:
        return False
    return url_has_allowed_host_and_scheme(
        url=url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    )


def safe_next_url(request: HttpRequest) -> str | None:
    """The `?next=` target of `request`, or None when it is absent or off-host.

    The adapter for the dominant call shape in this repo — 124 sites across 13 admin
    files on 2026-08-29, all of them written as::

        next_url = request.GET.get("next")     # <- attacker-controlled
        if next_url:
            messages.success(request, ...)
            return HttpResponseRedirect(next_url)
        return super().response_add(request, obj, post_url_continue)

    Swapping the first line for ``next_url = safe_next_url(request)`` closes the
    open redirect and leaves the other four lines untouched.

    ⚠️ THIS LIVES HERE, NOT IN AN APP. `project_management` first wrote it as a
    method on its own admin mixin, and that was right for one app; copied into
    thirteen it becomes thirteen predicates that will not all receive the next fix.
    The rule is the one that module's own docstring states: **two copies of a
    security predicate is one copy that misses the next patch.**

    Returning None rather than raising is deliberate. A refused target is not an
    error — the caller falls back to Django's default destination. A hostile
    `?next=` does not deserve an error page, only to be ignored.

    GET only. `?next=` is a query parameter by construction; a call site that also
    accepts it in the body should read both and pass the result to
    `is_safe_next_url` itself, as `drug_substance.views` does.
    """
    next_url = request.GET.get("next")
    return next_url if is_safe_next_url(request, next_url) else None


def is_safe_internal_path(url: str | None) -> bool:
    """True only for an INTERNAL, ROOT-RELATIVE path such as ``/projects/42/``.

    Strictly narrower than :func:`is_safe_next_url`, and deliberately so. That one
    answers "may I *redirect* there?" and therefore accepts an absolute URL on our
    own host. This one answers a different question — "may I write this straight
    into an ``href`` in a template?" — where the only defensible answer is a path
    with no scheme and no host at all.

    That distinction is not academic. The open-redirect campaign of 2026-08-29
    closed 124 ``?next=`` sites, and `tools/lint/check_open_redirects.py` guards
    them; its own docstring records that ``?back=`` — read today by `dls_parser`
    and `gel_analyzer` comparison views — is a DIFFERENT bug class it does not
    audit: a value landing in an ``href`` rather than in a redirect. Django's
    autoescaping does not stop ``javascript:``, so escaping is not the guard here.
    The predicate is.

    THE RULE, stated so it can be checked rather than trusted:

      1. non-empty, and starts with ``/``  -> no scheme, no bare relative path;
      2. does NOT start with ``//``        -> protocol-relative, i.e. a host;
      3. does NOT start with ``/\\``       -> Chrome reads the backslash as ``/``,
                                              so ``/\\evil.example`` is ``//evil.example``;
      4. and Django's own `url_has_allowed_host_and_scheme` with
         ``allowed_hosts=None`` agrees — an EMPTY allow-list, so any netloc at all
         fails, and a scheme without a host (``javascript:``, ``data:``) fails too.

    ⚠️ RULE 1 IS NOT REDUNDANT — measured, not assumed (Django 5.2.17)::

        url_has_allowed_host_and_scheme("evil.example.com", allowed_hosts=None) -> True
        url_has_allowed_host_and_scheme("projects/5/",      allowed_hosts=None) -> True

    Django's primitive accepts a BARE RELATIVE path: no netloc, no scheme, so
    nothing for it to refuse. The leading-slash test is the only thing rejecting
    those, and dropping it as "the primitive already covers it" would silently
    widen the accept-set. Rules 2 and 3 ARE redundant with rule 4 (``//evil`` and
    ``/\\evil`` both already return False) and are kept only so a reviewer can
    check the intent without reading Django's source.

    Rule 4 stays because it is the primitive that receives Django's security
    fixes, and because it refuses the scheme cases rules 1-3 say nothing about.

    Returns a bool, never raises: a refused ``back`` is not an error, it is simply
    not used. The caller falls back to its own default and reflects NOTHING.
    """
    if not url or not url.startswith("/"):
        return False
    if url.startswith("//") or url.startswith("/\\"):
        return False
    # allowed_hosts=None => empty allow-list => every netloc is refused.
    return url_has_allowed_host_and_scheme(url=url, allowed_hosts=None)


def safe_back_path(request: HttpRequest, param: str = "back") -> str | None:
    """The ``?back=`` path of `request` when it is an internal path, else None.

    The read-side adapter for :func:`is_safe_internal_path`. GET only, because a
    "come back here" hint is a query parameter by construction.
    """
    return request.GET.get(param) if is_safe_internal_path(request.GET.get(param)) else None


def safe_redirect_next(
    request: HttpRequest,
    next_url: str | None,
    fallback,
    *fallback_args,
    **fallback_kwargs,
) -> HttpResponseRedirect:
    """Redirect to `next_url` when safe, else to `fallback`.

    `fallback` is passed through to django.shortcuts.redirect — accepts a
    URL name, a model with get_absolute_url(), or a literal URL path.
    Extra positional/keyword args forward to `redirect()` for URL-name
    resolution (e.g. `pk=42`).

    Example:
        return safe_redirect_next(
            request,
            request.POST.get('next'),
            'milestone_tracker:milestone_list',
        )
    """
    if is_safe_next_url(request, next_url):
        return redirect(next_url)
    return redirect(fallback, *fallback_args, **fallback_kwargs)
