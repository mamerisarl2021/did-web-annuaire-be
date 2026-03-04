#!/usr/bin/env bash
set -euo pipefail

export PYTHONDONTWRITEBYTECODE=1
export PYTHONBUFFERED=1

echo "═══════════════════════════════════════════════════════════════"
echo "  Annuaire DID Backend — Starting"
echo "  Environment: ${DJANGO_ENV:-development}"
echo "═══════════════════════════════════════════════════════════════"

cd /app

# ── Migrations ──────────────────────────────────────────────────────────

echo "→ Running migrations..."
python -m src.manage migrate --noinput

# ── Collect static files ────────────────────────────────────────────────

echo "→ Collecting static files..."
python -m src.manage collectstatic --noinput --clear 2>/dev/null || true

echo "→ Creating superadmin..."
python -m src.manage createsuperadmin --no-input

echo "-> Bootstraping platform did..."
python -m src.manage bootstrap_platform_did --force


# ── Java check ──────────────────────────────────────────────────────────

echo "→ Verifying Java runtime..."
java -version 2>&1 | head -1

if [ -f /app/bin/ecdsa-extractor.jar ]; then
    echo "  ✓ Certificate extractor JAR found"
else
    echo "  ⚠ Certificate extractor JAR not found at /app/bin/ecdsa-extractor.jar"
fi

# ── Start Gunicorn ──────────────────────────────────────────────────────

echo ""
echo "→ Starting Gunicorn..."
exec gunicorn src.wsgi:application -c src/gunicorn.conf.py