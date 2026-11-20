# Resyncing `gel_analyzer` with ds-hub-django

Phoresis's `gel_analyzer` app was extracted from ds-hub-django on 2026-05-03 and both sides kept
moving. These scripts bring ds-hub's changes over **by three-way merge, never by copying a file**:
a copy silently drops Phoresis-side fixes (it did, once: `np.trapezoid`, the `SRC_DIR` model paths,
the Rf computed in the ladder lane's frame).

| Script | What it does |
|---|---|
| `merge3.py survey\|check\|write <path under gel_analyzer/> ...` | Merges Phoresis (`OURS_REF`) x ds-hub at extraction (`BASE_REF`) x ds-hub now (`THEIRS_REF`). Python goes through the import substitutions and ruff first; JS/HTML get the URL-root substitution (`/gel-analyzer/` -> `/`). |
| `show_conflicts.py <file> ...` | Prints the numbered conflict blocks with context. |
| `resolve_conflicts.py <file> <ours\|theirs\|both> [n=choice ...]` | Resolves blocks wholesale; edit by hand where the two sides must be combined. |

The three refs and the two repository paths are constants at the top of `merge3.py`: after a resync
lands, move `OURS_REF` to the Phoresis commit that holds it and `BASE_REF` to the ds-hub commit it
was merged from (`THEIRS_REF` of that run), so the next run merges only what is new.

Two things the merge cannot see:

- **Code ds-hub deleted and Phoresis still uses** disappears without a conflict (Phoresis had not
  changed it). After a merge, list the functions and routes of the previous Phoresis commit that no
  longer exist and decide each one.
- **Hub-only dependencies** (`process_development`, `project_management`, `authentication`, `base`,
  `Lane.process_sample`, `GelImage.project`, `GelAssay.analysis_type`, access groups, the export
  API) come along in clean hunks. Grep for them; Phoresis's equivalents live in `phoresis_core`
  (`safe_json`, `safe_redirect`, `stored_files`, `error_handling.helpers`) and in
  `gel_analyzer/access.py`, `services/purity.py`, `services/readout_publisher.py`.

`front_end_survey.txt` is the state of the JS/CSS/template merge when the back end landed
(new / same / merge / conflict, with the number of conflict blocks).
