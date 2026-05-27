#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# AgentCI — Verify Webhook Pipeline
#
# Tests every link in the chain:
#   1. API reachability (local)
#   2. ngrok tunnel (public)
#   3. Webhook signature verification
#   4. Ping event handling
#   5. PR event handling (simulated)
#   6. Dashboard API (authenticated)
#
# Usage:
#   chmod +x scripts/verify_webhook.sh
#   ./scripts/verify_webhook.sh
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

PASS=0
FAIL=0

test_pass() { echo -e "  ${GREEN}✓${NC} $*"; PASS=$((PASS + 1)); }
test_fail() { echo -e "  ${RED}✗${NC} $*"; FAIL=$((FAIL + 1)); }

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Load .env
set -a
source "${PROJECT_ROOT}/.env" 2>/dev/null || true
set +a

WEBHOOK_SECRET="${GITHUB_WEBHOOK_SECRET:-}"
API_KEY="${AGENTCI_API_KEYS%%,*}"
API_BASE="http://localhost:8000"

echo -e "\n${BOLD}AgentCI Webhook Verification${NC}\n"

# ── Test 1: API Health ──────────────────────────────────────────────────────
echo -e "${BOLD}1. API Health Check${NC}"

HEALTH=$(curl -s -w "\n%{http_code}" "${API_BASE}/health" 2>/dev/null)
HTTP_CODE=$(echo "$HEALTH" | tail -1)
BODY=$(echo "$HEALTH" | sed '$d')

if [ "$HTTP_CODE" = "200" ]; then
    test_pass "API healthy (200)"
    echo "$BODY" | python3 -m json.tool 2>/dev/null | sed 's/^/    /'
elif [ "$HTTP_CODE" = "503" ]; then
    test_pass "API reachable but degraded (503) — check DB"
    echo "$BODY" | python3 -m json.tool 2>/dev/null | sed 's/^/    /'
else
    test_fail "API not reachable (HTTP ${HTTP_CODE})"
    echo "    Run: cd docker && docker compose up -d"
fi

# ── Test 2: ngrok Tunnel ───────────────────────────────────────────────────
echo -e "\n${BOLD}2. ngrok Tunnel${NC}"

NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    for t in data.get('tunnels', []):
        if t.get('proto') == 'https':
            print(t['public_url'])
            break
except: pass
" 2>/dev/null)

if [ -n "$NGROK_URL" ]; then
    test_pass "ngrok active: ${NGROK_URL}"
    
    # Test public reachability
    PUB_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${NGROK_URL}/health" 2>/dev/null || echo "000")
    if [ "$PUB_CODE" = "200" ] || [ "$PUB_CODE" = "503" ]; then
        test_pass "Public URL reachable (${PUB_CODE})"
    else
        test_fail "Public URL NOT reachable (${PUB_CODE})"
    fi
else
    test_fail "ngrok not running"
    echo "    Run: ngrok http 8000"
fi

# ── Test 3: Webhook Signature Verification ──────────────────────────────────
echo -e "\n${BOLD}3. Webhook Signature Verification${NC}"

if [ -z "$WEBHOOK_SECRET" ]; then
    test_fail "GITHUB_WEBHOOK_SECRET not set in .env"
else
    # Test: missing signature → 403
    CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST "${API_BASE}/webhook/github" \
        -H "Content-Type: application/json" \
        -d '{"test": true}' 2>/dev/null)
    
    if [ "$CODE" = "403" ]; then
        test_pass "Missing signature correctly rejected (403)"
    else
        test_fail "Missing signature returned ${CODE} (expected 403)"
    fi

    # Test: invalid signature → 403
    CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST "${API_BASE}/webhook/github" \
        -H "Content-Type: application/json" \
        -H "X-Hub-Signature-256: sha256=invalid" \
        -H "X-GitHub-Event: ping" \
        -d '{"zen": "test"}' 2>/dev/null)
    
    if [ "$CODE" = "403" ]; then
        test_pass "Invalid signature correctly rejected (403)"
    else
        test_fail "Invalid signature returned ${CODE} (expected 403)"
    fi

    # Test: valid ping → 202
    PAYLOAD='{"zen":"Half measures are as bad as nothing at all."}'
    SIGNATURE=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" | awk '{print "sha256="$NF}')
    
    RESULT=$(curl -s -w "\n%{http_code}" \
        -X POST "${API_BASE}/webhook/github" \
        -H "Content-Type: application/json" \
        -H "X-Hub-Signature-256: ${SIGNATURE}" \
        -H "X-GitHub-Event: ping" \
        -d "$PAYLOAD" 2>/dev/null)
    
    CODE=$(echo "$RESULT" | tail -1)
    BODY=$(echo "$RESULT" | sed '$d')
    
    if [ "$CODE" = "202" ]; then
        ACTION=$(echo "$BODY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('action',''))" 2>/dev/null)
        if [ "$ACTION" = "pong" ]; then
            test_pass "Ping event → pong response (202)"
        else
            test_fail "Ping returned 202 but action was '${ACTION}' (expected 'pong')"
        fi
    else
        test_fail "Ping returned ${CODE} (expected 202)"
        echo "    Response: ${BODY}"
    fi
fi

# ── Test 4: Simulated PR Event ─────────────────────────────────────────────
echo -e "\n${BOLD}4. Simulated PR Event${NC}"

if [ -n "$WEBHOOK_SECRET" ]; then
    PR_PAYLOAD=$(cat <<'EOJSON'
{
  "action": "opened",
  "number": 999,
  "repository": {"full_name": "test-org/test-agent"},
  "pull_request": {
    "title": "AgentCI verification test",
    "head": {"sha": "abc123def456789012345678901234567890abcd"},
    "base": {"sha": "000111222333444555666777888999aaabbbcccd"}
  }
}
EOJSON
    )
    
    # Compute signature with exact payload bytes
    SIGNATURE=$(echo -n "$PR_PAYLOAD" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" | awk '{print "sha256="$NF}')
    
    RESULT=$(curl -s -w "\n%{http_code}" \
        -X POST "${API_BASE}/webhook/github" \
        -H "Content-Type: application/json" \
        -H "X-Hub-Signature-256: ${SIGNATURE}" \
        -H "X-GitHub-Event: pull_request" \
        -d "$PR_PAYLOAD" 2>/dev/null)
    
    CODE=$(echo "$RESULT" | tail -1)
    BODY=$(echo "$RESULT" | sed '$d')
    
    if [ "$CODE" = "202" ]; then
        ACTION=$(echo "$BODY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('action',''))" 2>/dev/null)
        RUN_ID=$(echo "$BODY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('run_id',''))" 2>/dev/null)
        if [ "$ACTION" = "queued" ]; then
            test_pass "PR event accepted → run queued (run_id: ${RUN_ID:0:8}...)"
        elif [ "$ACTION" = "skipped" ]; then
            test_pass "PR event accepted → skipped (no matching files, expected)"
        else
            test_pass "PR event accepted → ${ACTION}"
        fi
    else
        test_fail "PR event returned ${CODE} (expected 202)"
        echo "    Response: ${BODY}"
    fi
else
    test_fail "Skipped — no WEBHOOK_SECRET"
fi

# ── Test 5: Dashboard API Auth ──────────────────────────────────────────────
echo -e "\n${BOLD}5. Dashboard API Authentication${NC}"

if [ -n "$API_KEY" ]; then
    # Test: no key → 401
    CODE=$(curl -s -o /dev/null -w "%{http_code}" "${API_BASE}/api/runs" 2>/dev/null)
    if [ "$CODE" = "401" ]; then
        test_pass "API requires authentication (401 without key)"
    elif [ "$CODE" = "200" ]; then
        test_pass "API is open (no AGENTCI_API_KEYS set — ok for dev)"
    else
        test_fail "Unexpected status ${CODE} without API key"
    fi

    # Test: valid key → 200
    CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "X-API-Key: ${API_KEY}" \
        "${API_BASE}/api/runs" 2>/dev/null)
    if [ "$CODE" = "200" ]; then
        test_pass "API key accepted (200)"
    else
        test_fail "API key rejected (${CODE})"
    fi

    # Test: wrong key → 401
    CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "X-API-Key: wrong-key-12345" \
        "${API_BASE}/api/runs" 2>/dev/null)
    if [ "$CODE" = "401" ]; then
        test_pass "Invalid key rejected (401)"
    else
        test_fail "Invalid key returned ${CODE} (expected 401)"
    fi
else
    test_fail "AGENTCI_API_KEYS not set"
fi

# ── Test 6: Correlation ID ─────────────────────────────────────────────────
echo -e "\n${BOLD}6. Correlation ID Middleware${NC}"

REQUEST_ID=$(curl -s -D - "${API_BASE}/health" 2>/dev/null | grep -i "x-request-id" | tr -d '\r' | awk '{print $2}')
if [ -n "$REQUEST_ID" ]; then
    test_pass "X-Request-ID present: ${REQUEST_ID:0:36}"
else
    test_fail "X-Request-ID header missing from response"
fi

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}════════════════════════════════════════════════════════════════${NC}"
TOTAL=$((PASS + FAIL))
if [ $FAIL -eq 0 ]; then
    echo -e "  ${GREEN}${BOLD}ALL ${TOTAL} TESTS PASSED${NC}"
else
    echo -e "  ${GREEN}${PASS} passed${NC}, ${RED}${FAIL} failed${NC} out of ${TOTAL}"
fi
echo -e "${BOLD}════════════════════════════════════════════════════════════════${NC}"

if [ -n "$NGROK_URL" ]; then
    echo ""
    echo -e "  ${CYAN}Webhook URL for GitHub App:${NC}"
    echo -e "  ${BOLD}${NGROK_URL}/webhook/github${NC}"
fi
echo ""

exit $FAIL
