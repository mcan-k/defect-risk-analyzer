@echo off
chcp 65001 >nul 2>&1
echo ============================================================
echo   Defect Risk Analyzer - Durduruluyor
echo ============================================================
echo.

:: Kill uvicorn processes
echo [1/2] API sunucusu durduruluyor...
taskkill /F /FI "WINDOWTITLE eq DefectRisk-API" >nul 2>&1
taskkill /F /IM uvicorn.exe >nul 2>&1

:: Kill streamlit processes
echo [2/2] Dashboard durduruluyor...
taskkill /F /FI "WINDOWTITLE eq DefectRisk-Dashboard" >nul 2>&1
taskkill /F /IM streamlit.exe >nul 2>&1

:: Also kill any remaining python processes on our ports
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8501" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo.
echo ============================================================
echo   Tum servisler durduruldu.
echo ============================================================
echo.
pause
