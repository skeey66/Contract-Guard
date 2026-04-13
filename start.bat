@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo === K^&H2 시작 ===

:: 1. Ollama 시작
echo [1/3] Ollama 시작...
taskkill /f /im ollama.exe >nul 2>&1
timeout /t 1 /nobreak >nul
start /B "" ollama serve >nul 2>&1
timeout /t 3 /nobreak >nul
curl -s http://localhost:11434/api/tags >nul 2>&1 && (echo   -^> Ollama OK) || (echo   -^> Ollama 실패)

:: 2. 백엔드 시작
echo [2/3] 백엔드 시작 (port 8000)...
start /B "" cmd /c ".venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000" >nul 2>&1
set BACKEND_OK=0
for /L %%i in (1,1,15) do (
  if !BACKEND_OK!==0 (
    timeout /t 2 /nobreak >nul
    curl -s http://localhost:8000/health >nul 2>&1 && set BACKEND_OK=1
  )
)
if !BACKEND_OK!==1 (echo   -^> 백엔드 OK) else (echo   -^> 백엔드 실패 ^(30초 초과^))

:: 3. 프론트엔드 시작
echo [3/3] 프론트엔드 시작 (port 5173)...
start /B "" cmd /c "cd frontend && npm run dev" >nul 2>&1
timeout /t 3 /nobreak >nul
curl -s http://localhost:5173 >nul 2>&1 && (echo   -^> 프론트엔드 OK) || (echo   -^> 프론트엔드 실패)

echo.
echo === 실행 완료 ===
echo 브라우저에서 http://localhost:5173 접속하세요
pause
