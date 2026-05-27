#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# AgentCI — Production Deployment Setup
#
# This script:
#   1. Creates the .env file from .env.example if missing
#   2. Validates all required dependencies are installed
#   3. Builds and starts Docker services
#   4. Runs health checks against all services
#   5. Starts ngrok tunnel and prints the webhook URL
#
# Usage:
#   chmod +x scripts/deploy.sh
#   ./scripts/deploy.sh
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER_DIR="${PROJECT_ROOT}/docker"

log_info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step()  { echo -e "\n${BOLD}── Step $1: $2${NC}"; }

# ── Step 1: Check Prerequisites ─────────────────────────────────────────────
log_step 1 "Checking prerequisites"

MISSING=()

if ! command -v docker &>/dev/null; then
    MISSING+=("docker (https://docs.docker.com/get-docker/)")
fi

if ! docker compose version &>/dev/null 2>&1; then
    MISSING+=("docker compose v2 (included with Docker Desktop)")
fi

if ! command -v ngrok &>/dev/null; then
    MISSING+=("ngrok (https://ngrok.com/download or: brew install ngrok)")
fi

if ! command -v python3 &>/dev/null; then
    MISSING+=("python3 (https://python.org)")
fi

if [ ${#MISSING[@]} -gt 0 ]; then
    log_error "Missing required tools:"
    for tool in "${MISSING[@]}"; do
        echo "  • $tool"
    done
    exit 1
fi

log_ok "docker $(docker --version | grep -oP '\d+\.\d+\.\d+')"
log_ok "docker compose $(docker compose version --short)"
log_ok "ngrok $(ngrok version | grep -oP '\d+\.\d+\.\d+')"
log_ok "python3 $(python3 --version | cut -d' ' -f2)"

# ── Step 2: Environment File ────────────────────────────────────────────────
log_step 2 "Checking .env configuration"

ENV_FILE="${PROJECT_ROOT}/.env"

if [ ! -f "$ENV_FILE" ]; then
    log_warn ".env not found — creating from .env.example"
    cp "${PROJECT_ROOT}/.env.example" "$ENV_FILE"
    echo ""
    log_warn "You MUST edit .env before proceeding. At minimum set:"
    echo "  • At least one LLM API key (OPENAI_API_KEY, ANTHROPIC_API_KEY, or GOOGLE_API_KEY)"
    echo "  • GITHUB_WEBHOOK_SECRET (generate with: openssl rand -hex 20)"
    echo "  • AGENTCI_API_KEYS (any string for dashboard auth)"
    echo ""
    echo "  Edit: ${ENV_FILE}"
    echo ""
    read -p "Press Enter after editing .env to continue..."
fi

# Source .env to validate
set -a
source "$ENV_FILE" 2>/dev/null || true
set +a

# Validate critical vars
VALID=true

if [ -z "${GITHUB_WEBHOOK_SECRET:-}" ] || [ "$GITHUB_WEBHOOK_SECRET" = "generate-with-openssl-rand-hex-20" ]; then
    log_error "GITHUB_WEBHOOK_SECRET not set in .env"
    VALID=false
fi

if [ -z "${AGENTCI_API_KEYS:-}" ] || [ "$AGENTCI_API_KEYS" = "your-api-key-here" ]; then
    log_error "AGENTCI_API_KEYS not set in .env"
    VALID=false
fi

HAS_LLM_KEY=false
[ -n "${OPENAI_API_KEY:-}" ] && [ "${OPENAI_API_KEY}" != "sk-..." ] && HAS_LLM_KEY=true
[ -n "${ANTHROPIC_API_KEY:-}" ] && [ "${ANTHROPIC_API_KEY}" != "sk-ant-..." ] && HAS_LLM_KEY=true
[ -n "${GOOGLE_API_KEY:-}" ] && [ "${GOOGLE_API_KEY}" != "AIza..." ] && HAS_LLM_KEY=true

if [ "$HAS_LLM_KEY" = false ]; then
    log_error "No LLM API key set. At least one of OPENAI_API_KEY, ANTHROPIC_API_KEY, or GOOGLE_API_KEY is required."
    VALID=false
fi

if [ "$VALID" = false ]; then
    echo ""
    log_error "Fix the above issues in ${ENV_FILE} and re-run this script."
    exit 1
fi

log_ok "Environment validated"

# ── Step 3: Build and Start Services ────────────────────────────────────────
log_step 3 "Building and starting Docker services"

cd "$DOCKER_DIR"
docker compose --env-file "${PROJECT_ROOT}/.env" build --quiet 2>/dev/null || docker compose --env-file "${PROJECT_ROOT}/.env" build
docker compose --env-file "${PROJECT_ROOT}/.env" up -d

log_info "Waiting for services to become healthy..."
sleep 5

# ── Step 4: Health Checks ───────────────────────────────────────────────────
log_step 4 "Running health checks"

MAX_RETRIES=12
RETRY_INTERVAL=5

# Wait for PostgreSQL
log_info "Checking PostgreSQL..."
for i in $(seq 1 $MAX_RETRIES); do
    if docker compose exec -T postgres pg_isready -U agentci &>/dev/null; then
        log_ok "PostgreSQL ready"
        break
    fi
    [ $i -eq $MAX_RETRIES ] && { log_error "PostgreSQL failed to start"; docker compose logs postgres | tail -10; exit 1; }
    sleep $RETRY_INTERVAL
done

# Wait for Redis
log_info "Checking Redis..."
for i in $(seq 1 $MAX_RETRIES); do
    if docker compose exec -T redis redis-cli ping 2>/dev/null | grep -q PONG; then
        log_ok "Redis ready"
        break
    fi
    [ $i -eq $MAX_RETRIES ] && { log_error "Redis failed to start"; exit 1; }
    sleep $RETRY_INTERVAL
done

# Wait for API
log_info "Checking AgentCI API..."
for i in $(seq 1 $MAX_RETRIES); do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        log_ok "API healthy (200)"
        curl -s http://localhost:8000/health | python3 -m json.tool 2>/dev/null || true
        break
    elif [ "$HTTP_CODE" = "503" ]; then
        log_warn "API degraded (503) — check database connection"
        curl -s http://localhost:8000/health | python3 -m json.tool 2>/dev/null || true
        break
    fi
    [ $i -eq $MAX_RETRIES ] && { log_error "API failed to start"; docker compose logs api | tail -20; exit 1; }
    sleep $RETRY_INTERVAL
done

# Check Dashboard
log_info "Checking Dashboard..."
for i in $(seq 1 $MAX_RETRIES); do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:13000 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        log_ok "Dashboard ready at http://localhost:13000"
        break
    fi
    [ $i -eq $MAX_RETRIES ] && { log_warn "Dashboard not reachable yet — may still be building"; }
    sleep $RETRY_INTERVAL
done

# Check Temporal
log_info "Checking Temporal UI..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    log_ok "Temporal UI ready at http://localhost:8080"
else
    log_warn "Temporal UI not yet available (may take a minute)"
fi

# ── Step 5: Start ngrok ─────────────────────────────────────────────────────
log_step 5 "Starting ngrok tunnel"

# Kill any existing ngrok
pkill -f "ngrok http 8000" 2>/dev/null || true
sleep 1

# Start ngrok in background
ngrok http 8000 --log=stdout --log-level=warn > /tmp/ngrok-agentci.log 2>&1 &
NGROK_PID=$!
sleep 3

# Get the public URL
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    tunnels = data.get('tunnels', [])
    for t in tunnels:
        if t.get('proto') == 'https':
            print(t['public_url'])
            break
except: pass
" 2>/dev/null)

if [ -z "$NGROK_URL" ]; then
    log_error "Failed to get ngrok URL. Check if ngrok is authenticated:"
    echo "  ngrok config add-authtoken YOUR_TOKEN"
    echo "  (Get a free token at https://dashboard.ngrok.com)"
    kill $NGROK_PID 2>/dev/null
    exit 1
fi

WEBHOOK_URL="${NGROK_URL}/webhook/github"

log_ok "ngrok tunnel active"
echo ""

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}════════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  AgentCI Deployment Ready${NC}"
echo -e "${BOLD}════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${CYAN}Dashboard:${NC}      http://localhost:13000"
echo -e "  ${CYAN}API:${NC}            http://localhost:8000"
echo -e "  ${CYAN}API Health:${NC}     http://localhost:8000/health"
echo -e "  ${CYAN}Temporal UI:${NC}    http://localhost:8080"
echo -e "  ${CYAN}ngrok URL:${NC}      ${NGROK_URL}"
echo ""
echo -e "  ${GREEN}${BOLD}Webhook URL (copy this to GitHub App):${NC}"
echo -e "  ${BOLD}${WEBHOOK_URL}${NC}"
echo ""
echo -e "  ${CYAN}Webhook Secret:${NC} ${GITHUB_WEBHOOK_SECRET}"
echo -e "  ${CYAN}API Key:${NC}        ${AGENTCI_API_KEYS%%,*}"
echo ""
echo -e "${BOLD}── Next Steps ──${NC}"
echo ""
echo "  1. Go to: https://github.com/settings/apps/new"
echo "  2. Set Webhook URL to: ${WEBHOOK_URL}"
echo "  3. Set Webhook Secret to: ${GITHUB_WEBHOOK_SECRET}"
echo "  4. Enable permissions: Pull Requests (RW), Checks (RW), Contents (R)"
echo "  5. Subscribe to events: Pull Request"
echo "  6. Create the App → Generate Private Key → Install on your repo"
echo "  7. Add GITHUB_APP_ID and GITHUB_INSTALLATION_ID to .env"
echo "  8. Run: cd docker && docker compose restart api worker"
echo ""
echo -e "  ${YELLOW}ngrok is running in background (PID: ${NGROK_PID})${NC}"
echo -e "  ${YELLOW}To stop: kill ${NGROK_PID}${NC}"
echo -e "  ${YELLOW}To view logs: cat /tmp/ngrok-agentci.log${NC}"
echo ""
