@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo === K^&H2 시작 ===

:: 1. Ollama 시작
echo [1/3] Ollama 시작...
taskkill /f /im ollama.exe >nul 2>&1
timeout /t 1 /nobreak >nul
start "" ollama serve
timeout /t 3 /nobreak >nul
curl -s http://localhost:11434/api/tags >nul 2>&1 && (echo   -^> Ollama OK) || (echo   -^> Ollama 실패)

:: 2. 백엔드 시작
echo [2/3] 백엔드 시작 (port 8000)...
start "" cmd /c ".venv\Scripts\activate && uvicorn backend.app.main:app --host 0.0.0.0 --port 8000"
timeout /t 4 /nobreak >nul
curl -s http://localhost:8000/health >nul 2>&1 && (echo   -^> 백엔드 OK) || (echo   -^> 백엔드 실패)

:: 3. 프론트엔드 시작
echo [3/3] 프론트엔드 시작 (port 5173)...
start "" cmd /c "cd frontend && npm run dev"
timeout /t 3 /nobreak >nul
curl -s http://localhost:5173 >nul 2>&1 && (echo   -^> 프론트엔드 OK) || (echo   -^> 프론트엔드 실패)

echo.
echo === 실행 완료 ===
echo 브라우저에서 http://localhost:5173 접속하세요
pause
