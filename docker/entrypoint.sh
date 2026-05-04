#!/bin/sh
# Phoresis web/worker container entrypoint.
#
# Idempotent — safe to run on every container start. Run order matches
# spec section 10.3:
#   1. migrate           — applies pending schema + data migrations
#   2. collectstatic     — produces /srv/staticfiles for Caddy to serve
#   3. seed_groups       — idempotent (no-op after migrate; re-seeds if dropped)
#   4. seed_ladder_templates --skip-existing
#   5. create_initial_users --from-env --skip-existing
#   6. exec "$@"         — hands off to the per-container CMD (gunicorn / celery)
#
# Web container needs steps 1-5; worker / scheduler need ONLY 1 (migrate is
# safe & necessary because the worker imports the same models). The compose
# file passes `SKIP_COLLECTSTATIC=1` and `SKIP_SEEDS=1` to worker/scheduler
# to short-circuit those phases.

set -e

cd /app

echo "==> [entrypoint] migrate"
python manage.py migrate --noinput

if [ "${SKIP_COLLECTSTATIC:-0}" != "1" ]; then
    echo "==> [entrypoint] collectstatic"
    python manage.py collectstatic --noinput --clear
fi

if [ "${SKIP_SEEDS:-0}" != "1" ]; then
    echo "==> [entrypoint] seed_groups"
    python manage.py seed_groups

    echo "==> [entrypoint] seed_ladder_templates"
    python manage.py seed_ladder_templates --skip-existing || \
        echo "    (seed_ladder_templates not idempotent on this DB — continuing)"

    echo "==> [entrypoint] create_initial_users"
    python manage.py create_initial_users --from-env --skip-existing || \
        echo "    (no initial users env vars set — skipping)"
fi

echo "==> [entrypoint] exec $@"
exec "$@"
