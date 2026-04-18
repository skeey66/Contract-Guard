@echo off
chcp 65001 >nul

echo === K^&H2 종료 ===
taskkill /f /im ollama.exe >nul 2>&1 && (echo Ollama 종료) || (echo Ollama 미실행)

:: 백엔드: uvicorn 부모/자식 프로세스 모두 종료 (CommandLine 매칭)
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*uvicorn backend.app.main*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
echo 백엔드 종료

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173 ^| findstr LISTENING') do taskkill /f /pid %%a >nul 2>&1
echo 프론트엔드 종료
echo === 완료 ===
pause
