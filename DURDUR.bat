@echo off
chcp 65001 >nul 2>&1
echo.
echo   Defect Risk Analyzer durduruluyor...
echo.

for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8501" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo   Tum servisler durduruldu.
echo.
timeout /t 3 >nul
