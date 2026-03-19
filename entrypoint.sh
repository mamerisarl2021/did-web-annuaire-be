#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────
#  Root phase – fix volume permissions, then re‑exec as appuser
# ─────────────────────────────────────────────────────────────────────
if [ "$(id -u)" = "0" ]; then
    echo "→ Fixing permissions on media and dids volumes..."
    # mkdir -p /app/mediafiles/uploads /app/data/dids
    chown -R appuser:appuser /app/mediafiles /app/data/dids

    # Re‑execute this script as the appuser
    exec su-exec appuser "$0" "$@"
fi

# ─────────────────────────────────────────────────────────────────────
#  From here on, we are running as appuser
# ─────────────────────────────────────────────────────────────────────
export PYTHONDONTWRITEBYTECODE=1
export PYTHONBUFFERED=1

echo "═══════════════════════════════════════════════════════════════"
echo "  Annuaire DID Backend — Starting"
echo "  Environment: ${DJANGO_ENV:-development}"
echo "═══════════════════════════════════════════════════════════════"

cd /app

# ── Migrations ─────────────────────────────────────────────────────
echo "→ Running migrations..."
python -m src.manage migrate --noinput

# ── Collect static files ────────────────────────────────────────────
echo "→ Collecting static files..."
python -m src.manage collectstatic --noinput --clear 2>/dev/null || true

echo "→ Creating superadmin..."
python -m src.manage createsuperadmin --no-input

echo "→ Bootstrapping platform did..."
python -m src.manage bootstrap_platform_did --force

# ── Java check ─────────────────────────────────────────────────────
echo "→ Verifying Java runtime..."
java -version 2>&1 | head -1

if [ -f /app/bin/ecdsa-extractor.jar ]; then
    echo "  ✓ Certificate extractor JAR found"
else
    echo "  ⚠ Certificate extractor JAR not found at /app/bin/ecdsa-extractor.jar"
fi

# ── Start Gunicorn ─────────────────────────────────────────────────
echo ""
echo "→ Starting Gunicorn..."
exec gunicorn src.wsgi:application -c src/gunicorn.conf.py