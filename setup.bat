@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo === Contract-Guard 초기 설정 ===
echo.

set FAIL=0

:: 1. Python 확인
echo [1/7] Python 확인...
where python >nul 2>&1
if errorlevel 1 (
  echo   -^> Python을 찾을 수 없습니다. https://www.python.org/downloads/ 에서 3.11+ 설치
  set FAIL=1
  goto :prereq_check
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo   -^> Python !PYVER!

:: 2. Node.js 확인
echo [2/7] Node.js 확인...
where node >nul 2>&1
if errorlevel 1 (
  echo   -^> Node.js를 찾을 수 없습니다. https://nodejs.org 에서 18+ 설치
  set FAIL=1
  goto :prereq_check
)
for /f %%v in ('node --version 2^>^&1') do set NODEVER=%%v
echo   -^> Node.js !NODEVER!

:: 3. Ollama 확인 (없어도 진행 가능, 경고만)
echo [3/7] Ollama 확인...
where ollama >nul 2>&1
if errorlevel 1 (
  echo   -^> [경고] Ollama가 설치되지 않았습니다. https://ollama.com/download 에서 설치 후
  echo            "ollama pull exaone3.5:7.8b" 을 실행하세요. 설치 없이도 setup은 계속됩니다.
) else (
  echo   -^> Ollama 설치됨
)

:prereq_check
if !FAIL!==1 (
  echo.
  echo === 사전 조건 미충족 — setup 중단 ===
  pause
  exit /b 1
)

:: 4. .env 생성
echo [4/7] .env 파일 확인...
if exist ".env" (
  echo   -^> .env 이미 존재 (그대로 사용)
) else (
  if exist ".env.example" (
    copy /Y .env.example .env >nul
    echo   -^> .env.example 을 .env 로 복사
  ) else (
    echo   -^> [경고] .env.example 도 없음. 환경변수 미설정 상태로 진행
  )
)

:: 5. Python 가상환경 + 의존성
echo [5/7] Python 가상환경 및 패키지 설치...
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 (
    echo   -^> venv 생성 실패
    pause
    exit /b 1
  )
  echo   -^> venv 생성 완료
) else (
  echo   -^> venv 이미 존재
)
.venv\Scripts\python.exe -m pip install --upgrade pip >nul
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 (
  echo   -^> pip install 실패
  pause
  exit /b 1
)
echo   -^> Python 패키지 설치 완료

:: 6. 프론트엔드 패키지 설치
echo [6/7] 프론트엔드 패키지 설치...
if exist "frontend\node_modules" (
  echo   -^> node_modules 이미 존재 (npm install 생략)
) else (
  pushd frontend
  call npm install
  if errorlevel 1 (
    popd
    echo   -^> npm install 실패
    pause
    exit /b 1
  )
  popd
  echo   -^> npm 패키지 설치 완료
)

:: 7. ChromaDB 지식베이스 빌드 (이미 있으면 건너뜀)
echo [7/7] ChromaDB 지식베이스 확인...
if exist "data\chroma\chroma.sqlite3" (
  echo   -^> 기존 KB 발견 (재빌드 생략). 새로 빌드하려면 data\chroma 폴더 삭제 후 재실행
) else (
  echo   -^> KB 없음. 내장 데이터로 빌드 시작 (수 분 소요)...
  .venv\Scripts\python.exe -m backend.scripts.build_kb
  if errorlevel 1 (
    echo   -^> KB 빌드 실패. 수동으로 "python -m backend.scripts.build_kb" 실행 필요
  ) else (
    echo   -^> KB 빌드 완료
  )
)

echo.
echo === 설정 완료 ===
echo.
echo 다음 단계:
echo   1. Ollama 모델이 없다면: ollama pull exaone3.5:7.8b
echo   2. 서버 실행: start.bat
echo   3. 브라우저: http://localhost:5173
pause
