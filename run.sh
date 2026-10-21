#!/bin/bash
# Simple non-Docker launcher for a quick local demo. Docker Compose is preferred for normal use.

# Always run from the project folder, even if this script is called from somewhere else.
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Load environment variables
if [ -f .env ]; then
    echo "[run.sh] Loading .env file"
    # Export vars without comments
    export $(grep -v '^#' .env | xargs)
else
    echo "[run.sh] Warning: .env file not found, using default configurations"
fi

# Fallback defaults if not set
GROQ_API_KEY=${GROQ_API_KEY:-""}
MODEL_NAME=${MODEL_NAME:-"openai/gpt-oss-20b"}
ANSWER_MODE=${ANSWER_MODE:-"groq"}

export ML_URL=${ML_URL:-"http://127.0.0.1:5001"}
export DBMS_URL=${DBMS_URL:-"http://127.0.0.1:5002"}
export CLOUD_URL=${CLOUD_URL:-"http://127.0.0.1:5003"}

# Detect python interpreter with uvicorn installed
if python -c "import uvicorn" 2>/dev/null; then
    PYTHON_CMD="python"
elif python3 -c "import uvicorn" 2>/dev/null; then
    PYTHON_CMD="python3"
else
    echo "[run.sh] Error: 'uvicorn' is not installed in the current Python environment."
    echo "[run.sh] Please run: pip install -r requirements.txt"
    exit 1
fi

# These variables remember the three background subject-service process IDs.
ML_PID=""
DBMS_PID=""
CLOUD_PID=""

# Stop all background services neatly when the user presses Ctrl+C.
cleanup() {
    echo ""
    echo "[run.sh] Catching interrupt signal. Cleaning up background services..."
    for pid in "$ML_PID" "$DBMS_PID" "$CLOUD_PID"; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "[run.sh] Sending SIGTERM to service PID $pid"
            kill -15 "$pid" 2>/dev/null
        fi
    done
    exit 0
}

# Trap SIGINT and SIGTERM to run cleanup
trap cleanup SIGINT SIGTERM

echo "[run.sh] Starting EduMesh services using $PYTHON_CMD..."

# 1. Start one copy of the reusable service file as the ML subject.
export SUBJECT="ML"
$PYTHON_CMD -m uvicorn service:app --host 127.0.0.1 --port 5001 > ml.log 2>&1 &
ML_PID=$!
echo "[run.sh] Started ML Service (PID: $ML_PID) on port 5001"

# 2. Start another copy as the DBMS subject.
export SUBJECT="DBMS"
$PYTHON_CMD -m uvicorn service:app --host 127.0.0.1 --port 5002 > dbms.log 2>&1 &
DBMS_PID=$!
echo "[run.sh] Started DBMS Service (PID: $DBMS_PID) on port 5002"

# 3. Start another copy as the Cloud subject.
export SUBJECT="CLOUD"
$PYTHON_CMD -m uvicorn service:app --host 127.0.0.1 --port 5003 > cloud.log 2>&1 &
CLOUD_PID=$!
echo "[run.sh] Started CLOUD Service (PID: $CLOUD_PID) on port 5003"

# Wait a brief moment for services to bind
sleep 2

# 4. Keep the gateway in the foreground so Ctrl+C can stop the entire demo.
echo "[run.sh] Starting Gateway on port 5000 in foreground..."
$PYTHON_CMD -m uvicorn gateway:app --host 127.0.0.1 --port 5000
