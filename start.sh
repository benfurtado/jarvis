#!/bin/bash
# ============================================================
# Jarvis AI OS — One-Shot Setup & Run Script
# Run: chmod +x start.sh && ./start.sh
# ============================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color
BOLD='\033[1m'

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$PROJECT_DIR/server.log"
PORT=5000

echo -e "${CYAN}${BOLD}"
echo "╔══════════════════════════════════════════════╗"
echo "║       🚀 JARVIS AI OS — STARTUP SCRIPT       ║"
echo "╚══════════════════════════════════════════════╝"
echo -e "${NC}"

# ============================================================
# 1. CHECK PYTHON
# ============================================================
echo -e "${YELLOW}[1/6]${NC} Checking Python..."
if command -v python3 &>/dev/null; then
    PYTHON=$(command -v python3)
    PY_VERSION=$($PYTHON --version 2>&1)
    echo -e "  ${GREEN}✓${NC} $PY_VERSION at $PYTHON"
else
    echo -e "  ${RED}✗ Python3 not found. Install Python 3.10+ first.${NC}"
    exit 1
fi

# ============================================================
# 2. INSTALL DEPENDENCIES
# ============================================================
echo -e "${YELLOW}[2/6]${NC} Installing dependencies..."

# Check if pip works normally or needs --break-system-packages
PIP_FLAGS=""
if $PYTHON -m pip install --help 2>&1 | grep -q "break-system-packages"; then
    PIP_FLAGS="--break-system-packages"
fi

$PYTHON -m pip install $PIP_FLAGS --quiet --upgrade pip 2>/dev/null || true

if [ -f "$PROJECT_DIR/requirements.txt" ]; then
    echo -e "  Installing from requirements.txt..."
    $PYTHON -m pip install $PIP_FLAGS --quiet -r "$PROJECT_DIR/requirements.txt" 2>&1 | tail -3
    echo -e "  ${GREEN}✓${NC} All Python packages installed"
else
    echo -e "  ${RED}✗ requirements.txt not found!${NC}"
    echo -e "  Installing core packages manually..."
    $PYTHON -m pip install $PIP_FLAGS --quiet \
        flask flask-cors flask-jwt-extended flask-limiter flask-socketio eventlet \
        langchain langchain-groq langgraph langchain_community langgraph-checkpoint-sqlite \
        bcrypt python-dotenv psutil pillow mss apscheduler requests websocket-client \
        google-api-python-client google-auth-httplib2 google-auth-oauthlib pydantic \
        2>&1 | tail -3
    echo -e "  ${GREEN}✓${NC} Core packages installed"
fi

# ============================================================
# 3. CHECK .env FILE
# ============================================================
echo -e "${YELLOW}[3/6]${NC} Checking configuration..."

if [ -f "$PROJECT_DIR/.env" ]; then
    echo -e "  ${GREEN}✓${NC} .env file found"

    # Check critical env vars
    if grep -q "GROQ_API_KEY=gsk_" "$PROJECT_DIR/.env"; then
        echo -e "  ${GREEN}✓${NC} GROQ_API_KEY is set"
    else
        echo -e "  ${RED}✗${NC} GROQ_API_KEY not set in .env — LLM won't work!"
        echo -e "    Get one at: ${CYAN}https://console.groq.com/keys${NC}"
    fi
else
    echo -e "  ${YELLOW}⚠${NC} No .env file found, creating template..."
    cat > "$PROJECT_DIR/.env" <<'ENVFILE'
# Jarvis AI OS Configuration
GROQ_API_KEY=your-groq-api-key-here
SECRET_KEY=jarvis-super-secret-key-change-me-in-production
ADMIN_USERNAME=admin
ADMIN_PASSWORD=jarvis2024
LLM_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
PRODUCTION=true
ALLOWED_ORIGINS=*
ALLOWED_DIRS=/root/projects,/tmp
ENVFILE
    echo -e "  ${YELLOW}⚠${NC} Edit .env and set your GROQ_API_KEY!"
fi

# ============================================================
# 4. CREATE REQUIRED DIRECTORIES
# ============================================================
echo -e "${YELLOW}[4/6]${NC} Setting up directories..."

mkdir -p "$PROJECT_DIR/gmail_data"
mkdir -p "$PROJECT_DIR/data"
mkdir -p "$PROJECT_DIR/temp"
mkdir -p "$PROJECT_DIR/backups"
echo -e "  ${GREEN}✓${NC} Directories ready"

# Check Gmail setup
if [ -f "$PROJECT_DIR/gmail_data/credentials.json" ]; then
    echo -e "  ${GREEN}✓${NC} Gmail credentials.json found"
    if [ -f "$PROJECT_DIR/gmail_data/token.json" ]; then
        echo -e "  ${GREEN}✓${NC} Gmail token.json found (authorized)"
    else
        echo -e "  ${YELLOW}⚠${NC} Gmail not authorized yet"
        echo -e "    After startup, visit: ${CYAN}http://YOUR_IP:$PORT/api/gmail/authorize${NC}"
    fi
else
    echo -e "  ${YELLOW}⚠${NC} Gmail not configured (optional)"
    echo -e "    To enable: place credentials.json in gmail_data/"
fi

# ============================================================
# 5. KILL EXISTING INSTANCE
# ============================================================
echo -e "${YELLOW}[5/6]${NC} Checking for existing Jarvis instance..."

EXISTING_PID=$(lsof -t -i :$PORT 2>/dev/null || true)
if [ -n "$EXISTING_PID" ]; then
    echo -e "  Stopping existing process on port $PORT (PID: $EXISTING_PID)..."
    kill -9 $EXISTING_PID 2>/dev/null || true
    sleep 2
    echo -e "  ${GREEN}✓${NC} Old instance stopped"
else
    echo -e "  ${GREEN}✓${NC} Port $PORT is free"
fi

# ============================================================
# 6. START JARVIS
# ============================================================
echo -e "${YELLOW}[6/6]${NC} Starting Jarvis server..."

cd "$PROJECT_DIR"

# Start in background with logging
nohup $PYTHON main.py > "$LOG_FILE" 2>&1 &
JARVIS_PID=$!

echo -e "  PID: $JARVIS_PID"
echo -e "  Log: $LOG_FILE"

# Wait for server to come up
echo -ne "  Waiting for server"
for i in {1..15}; do
    if curl -s http://localhost:$PORT/ > /dev/null 2>&1; then
        break
    fi
    echo -ne "."
    sleep 1
done
echo ""

# Verify
if curl -s http://localhost:$PORT/ > /dev/null 2>&1; then
    # Get the server IP
    SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

    echo ""
    echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════╗"
    echo -e "║           ✅ JARVIS IS RUNNING!               ║"
    echo -e "╚══════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${BOLD}Dashboard:${NC}  ${CYAN}http://$SERVER_IP:$PORT${NC}"
    echo -e "  ${BOLD}Login:${NC}      admin / jarvis2024"
    echo -e "  ${BOLD}Gmail Auth:${NC} ${CYAN}http://$SERVER_IP:$PORT/api/gmail/authorize${NC}"
    echo -e "  ${BOLD}API Status:${NC} ${CYAN}http://$SERVER_IP:$PORT/api/gmail/status${NC}"
    echo ""
    echo -e "  ${BOLD}Logs:${NC}       tail -f $LOG_FILE"
    echo -e "  ${BOLD}Stop:${NC}       kill $JARVIS_PID"
    echo ""

    # Show tool count from log
    TOOLS=$(grep "TOOL_REGISTRY loaded" "$LOG_FILE" 2>/dev/null | tail -1 || true)
    if [ -n "$TOOLS" ]; then
        echo -e "  ${GREEN}✓${NC} $TOOLS" | sed 's/.*INFO - //'
    fi

    EMAIL_CHECK=$(grep "email tools confirmed" "$LOG_FILE" 2>/dev/null | tail -1 || true)
    if [ -n "$EMAIL_CHECK" ]; then
        echo -e "  ${GREEN}✓${NC} $EMAIL_CHECK" | sed 's/.*INFO - //'
    fi
    echo ""
else
    echo ""
    echo -e "${RED}${BOLD}✗ Server failed to start!${NC}"
    echo -e "  Check logs: ${CYAN}cat $LOG_FILE${NC}"
    echo ""
    echo -e "  Last 10 lines:"
    tail -10 "$LOG_FILE" 2>/dev/null
    exit 1
fi
