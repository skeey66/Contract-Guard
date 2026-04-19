#!/bin/bash
set -e

cd "$(dirname "$0")"

# .env 파일에서 환경변수 로드
export $(grep -v '^#' .env | grep -v '^$' | xargs)

echo "=== K&H2 시작 ==="

# 1. Ollama 시작
echo "[1/3] Ollama 시작 (NUM_PARALLEL=$OLLAMA_NUM_PARALLEL)..."
pkill -f "ollama serve" 2>/dev/null || true
sleep 1
OLLAMA_NUM_PARALLEL=$OLLAMA_NUM_PARALLEL ollama serve > /dev/null 2>&1 &
sleep 3
curl -s http://localhost:11434/api/tags > /dev/null && echo "  -> Ollama OK" || echo "  -> Ollama 실패"

# 2. 백엔드 시작
echo "[2/3] 백엔드 시작 (port 8000)..."
pkill -f "uvicorn backend.app" 2>/dev/null || true
sleep 1
.venv/bin/uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000 > /dev/null 2>&1 &
sleep 4
curl -s http://localhost:8000/health > /dev/null && echo "  -> 백엔드 OK" || echo "  -> 백엔드 실패"

# 3. 프론트엔드 시작
echo "[3/3] 프론트엔드 시작 (port 5173)..."
cd frontend && npm run dev > /dev/null 2>&1 &
cd ..
sleep 3
curl -s http://localhost:5173 > /dev/null && echo "  -> 프론트엔드 OK" || echo "  -> 프론트엔드 실패"

echo ""
echo "=== 실행 완료 ==="
echo "브라우저에서 http://localhost:5173 접속하세요"
