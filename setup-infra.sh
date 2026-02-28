#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# setup-infra.sh — One-time setup for DID infrastructure on VPS
#
# Run this ONCE after placing files in the correct directories.
# CI/CD does NOT touch these stacks — they stay running permanently.
#
# Directory layout on VPS:
#   ~/app/did-web-annuaire-backend/staging/  ← backend (managed by CI/CD)
#   ~/app/keyfactor/                         ← EJBCA + SignServer
#   ~/DIF/                                   ← Universal Resolver + Registrar
###############################################################################

echo "═══════════════════════════════════════════════════════════════"
echo "  DID Directory — Infrastructure Setup"
echo "═══════════════════════════════════════════════════════════════"

# 1. Create shared network
echo ""
echo "→ Creating shared Docker network: annuaire_staging_net"
docker network create annuaire_staging_net 2>/dev/null || echo "  (already exists)"

# 2. Start backend stack first (creates named volumes)
#BACKEND_DIR=~/apps/did-web-annuaire-backend/staging
#echo ""
#echo "→ Starting backend stack ($BACKEND_DIR)"
#cd "$BACKEND_DIR"
#docker compose -f compose.yml up -d
#echo "  ✓ Backend stack up"

# 3. Start DIF stacks (resolver + registrar)
DIF_DIR=~/apps/DIF
echo ""
echo "→ Starting Universal Resolver ($DIF_DIR)"
cd "$DIF_DIR"
docker compose -f universalresolver.yml up -d
echo "  ✓ Resolver up"

echo ""
echo "→ Starting Universal Registrar ($DIF_DIR)"
docker compose -f universalregistrar.yml up -d
echo "  ✓ Registrar up"

# 4. Start Keyfactor stacks
KF_DIR=~/apps/keyfactor
echo ""
echo "→ Starting SignServer CE ($KF_DIR)"
cd "$KF_DIR"
docker compose -f keyfactor-signserver-ce.yml up -d
echo "  ✓ SignServer up"

echo ""
echo "→ Starting EJBCA CE ($KF_DIR)"
docker compose -f keyfactor-ejbca.yml up -d
echo "  ✓ EJBCA up"

# 5. Summary
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  ✅  All infrastructure stacks are running"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  Endpoints (via nginx on :8086):"
echo "    Backend API        http://HOST:8086/api/"
echo "    Resolve a DID      http://HOST:8086/resolver/1.0/identifiers/did:web:example.com"
echo "    Create a DID       POST http://HOST:8086/registrar/1.0/create"
echo "    SignServer          http://HOST:8086/signserver/"
echo ""
echo "  Direct access:"
echo "    SignServer Admin    https://HOST:8443/signserver/"
echo "    EJBCA Admin         https://HOST:446/ejbca/"
echo ""
echo "  CI/CD only touches:  ~/app/did-web-annuaire-backend/staging/"
echo "  Everything else stays running permanently."
echo ""
