# `dashboard`

Phoresis landing page — KPI cards + recent gels + quick actions.

## Purpose

Single home view (`/`) showing:
- 4 KPI cards (total gels, total analyses, pending, new in 7d) — animated via CountUp.js.
- Up to 6 recent gels grid with thumbnails.
- Empty state with upload CTA when no gels exist yet.

## Public surface

- `dashboard:home` — `/` (login required).
- `services.get_kpis()` and `services.get_recent_gels(limit=6)` are reusable from any app that wants the same aggregates.

## Key files

| File | Purpose |
|---|---|
| `views.py` | home_view |
| `services.py` | get_kpis(), get_recent_gels() |
| `templates/dashboard/home.html` | KPI grid + recent gels |
| `nav.py` | Dashboard registration in nav_registry (Management group, shortcut `D`) |

## Integration

- Imports `gel_analyzer.models.GelImage` and `GelAnalysis` lazily inside `services.py` to avoid circular imports if dashboard ever loads before gel_analyzer.
- Adding a new KPI card: extend `services.DashboardKPIs` and add a `{% kpi %}` cell in the template grid.
