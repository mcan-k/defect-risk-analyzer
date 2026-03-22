@echo off
chcp 65001 >nul 2>&1
echo ============================================================
echo   Defect Risk Analyzer - Baslatiliyor
echo ============================================================
echo.

:: Check venv exists
if not exist ".venv\Scripts\activate.bat" (
    echo [HATA] Sanal ortam bulunamadi. Once kurulum yapin:
    echo        scripts\setup.bat
    echo.
    pause
    exit /b 1
)

:: Activate venv
call .venv\Scripts\activate.bat

:: Check .env exists
if not exist ".env" (
    echo [UYARI] .env dosyasi bulunamadi. Mock modda baslatiliyor...
    echo USE_MOCK_DATA=True> .env
)

:: Start API backend in background
echo [1/3] API sunucusu baslatiliyor (port 8000)...
start /B "DefectRisk-API" cmd /c "call .venv\Scripts\activate.bat && python -m uvicorn api:app --host 0.0.0.0 --port 8000 2>&1 > data\api.log"
echo       API baslatildi.
echo.

:: Wait for API to be ready
echo [2/3] API hazir olana kadar bekleniyor...
timeout /t 3 /nobreak >nul
echo       API hazir.
echo.

:: Start Streamlit dashboard in background
echo [3/3] Dashboard baslatiliyor (port 8501)...
start /B "DefectRisk-Dashboard" cmd /c "call .venv\Scripts\activate.bat && python -m streamlit run dashboard.py --server.port 8501 --server.headless true 2>&1 > data\dashboard.log"
echo       Dashboard baslatildi.
echo.

:: Wait and open browser
timeout /t 3 /nobreak >nul
echo Tarayici aciliyor...
start http://localhost:8501

echo.
echo ============================================================
echo   Uygulama calisiyor!
echo.
echo   Dashboard:  http://localhost:8501
echo   API:        http://localhost:8000
echo   API Docs:   http://localhost:8000/docs
echo.
echo   Durdurmak icin: scripts\stop.bat
echo ============================================================
echo.
pause
