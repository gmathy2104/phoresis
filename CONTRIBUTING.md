# Contributing to Phoresis

## Tests

Run the full suite with:

```bash
.venv/Scripts/python.exe -m pytest -v
```

### Speed-up: `--reuse-db`

For long-running suites, you can opt into reusing the test database between runs:

```bash
.venv/Scripts/python.exe -m pytest -v --reuse-db
```

This skips schema migration on subsequent runs. **Caveat:** if you've added a new migration, you must use `--create-db` once to refresh the schema:

```bash
.venv/Scripts/python.exe -m pytest -v --create-db
```

We don't enable `--reuse-db` by default in `pyproject.toml` because it's a frequent source of stale-schema test failures during phases of rapid migration churn.
