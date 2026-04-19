#!/bin/bash
# Contract-Guard 초기 설정 스크립트 (macOS / Linux)
# Windows 사용자는 setup.bat 사용

set -e
cd "$(dirname "$0")"

echo "=== Contract-Guard 초기 설정 ==="
echo

FAIL=0

# 1. Python 확인 (3.11+)
echo "[1/7] Python 확인..."
if command -v python3 >/dev/null 2>&1; then
  PYBIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYBIN="python"
else
  echo "  -> Python을 찾을 수 없습니다. https://www.python.org/downloads/ 에서 3.11+ 설치"
  FAIL=1
fi

if [ "$FAIL" -eq 0 ]; then
  PYVER=$($PYBIN --version 2>&1 | awk '{print $2}')
  echo "  -> Python $PYVER ($PYBIN)"
fi

# 2. Node.js 확인 (18+)
echo "[2/7] Node.js 확인..."
if command -v node >/dev/null 2>&1; then
  NODEVER=$(node --version)
  echo "  -> Node.js $NODEVER"
else
  echo "  -> Node.js를 찾을 수 없습니다. https://nodejs.org 에서 18+ 설치"
  FAIL=1
fi

# 3. Ollama 확인 (없어도 setup은 계속, 경고만)
echo "[3/7] Ollama 확인..."
if command -v ollama >/dev/null 2>&1; then
  echo "  -> Ollama 설치됨"
else
  echo "  -> [경고] Ollama가 설치되지 않았습니다. https://ollama.com/download 에서 설치 후"
  echo "          'ollama pull exaone3.5:7.8b' 을 실행하세요."
fi

if [ "$FAIL" -eq 1 ]; then
  echo
  echo "=== 사전 조건 미충족 — setup 중단 ==="
  exit 1
fi

# 4. .env 생성
echo "[4/7] .env 파일 확인..."
if [ -f ".env" ]; then
  echo "  -> .env 이미 존재 (그대로 사용)"
elif [ -f ".env.example" ]; then
  cp .env.example .env
  echo "  -> .env.example 을 .env 로 복사"
else
  echo "  -> [경고] .env.example 도 없음. 환경변수 미설정 상태로 진행"
fi

# 5. Python 가상환경 + 의존성
echo "[5/7] Python 가상환경 및 패키지 설치..."
if [ ! -x ".venv/bin/python" ]; then
  $PYBIN -m venv .venv
  echo "  -> venv 생성 완료"
else
  echo "  -> venv 이미 존재"
fi
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r backend/requirements.txt
echo "  -> Python 패키지 설치 완료"

# 6. 프론트엔드 패키지 설치
echo "[6/7] 프론트엔드 패키지 설치..."
if [ -d "frontend/node_modules" ]; then
  echo "  -> node_modules 이미 존재 (npm install 생략)"
else
  (cd frontend && npm install)
  echo "  -> npm 패키지 설치 완료"
fi

# 7. ChromaDB 지식베이스 빌드 (이미 있으면 건너뜀)
echo "[7/7] ChromaDB 지식베이스 확인..."
if [ -f "data/chroma/chroma.sqlite3" ]; then
  echo "  -> 기존 KB 발견 (재빌드 생략). 새로 빌드하려면 data/chroma 폴더 삭제 후 재실행"
else
  echo "  -> KB 없음. 내장 데이터로 빌드 시작 (수 분 소요)..."
  if .venv/bin/python -m backend.scripts.build_kb; then
    echo "  -> KB 빌드 완료"
  else
    echo "  -> KB 빌드 실패. 수동으로 'python -m backend.scripts.build_kb' 실행 필요"
  fi
fi

# start.sh 실행권한 부여
if [ -f "start.sh" ] && [ ! -x "start.sh" ]; then
  chmod +x start.sh
fi
if [ -f "stop.sh" ] && [ ! -x "stop.sh" ]; then
  chmod +x stop.sh
fi

echo
echo "=== 설정 완료 ==="
echo
echo "다음 단계:"
echo "  1. Ollama 모델이 없다면: ollama pull exaone3.5:7.8b"
echo "  2. 서버 실행: ./start.sh"
echo "  3. 브라우저: http://localhost:5173"
