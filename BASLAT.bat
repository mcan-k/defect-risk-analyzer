@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo.
echo   ========================================================
echo   Defect Risk Analyzer
echo   ========================================================
echo.

REM --- Python kontrolu ---
python --version >nul 2>&1
if errorlevel 1 (
    echo   [HATA] Python bulunamadi!
    echo.
    echo   Python 3.11 veya ustu yuklu olmali.
    echo   Indirmek icin:  https://www.python.org/downloads/
    echo.
    echo   ONEMLI: Kurulum sirasinda "Add Python to PATH" secenegini
    echo   isaretlemeyi unutmayin.
    echo.
    pause
    exit /b 1
)

echo   Python bulundu:
python --version
echo.

REM --- Ilk calistirma: sanal ortam + bagimliliklar ---
if not exist ".venv\Scripts\activate.bat" (
    echo   Ilk calistirma tespit edildi - kurulum basliyor...
    echo   Bu islem sadece bir kez yapilir, 1-2 dakika surebilir.
    echo.

    echo   [1/4] Sanal ortam olusturuluyor...
    python -m venv .venv
    if errorlevel 1 (
        echo   [HATA] Sanal ortam olusturulamadi.
        pause
        exit /b 1
    )

    call .venv\Scripts\activate.bat

    echo   [2/4] Bagimliliklar yukleniyor...
    pip install --upgrade pip >nul 2>&1
    pip install -r requirements.txt
    if errorlevel 1 (
        echo   [HATA] Bagimliliklar yuklenemedi.
        pause
        exit /b 1
    )

    echo   [3/4] Klasorler hazirlaniyor...
    if not exist "data" mkdir data

    echo   [4/4] Ayarlar hazirlaniyor...
    if not exist ".env" (
        if exist ".env.example" (
            copy .env.example .env >nul
        ) else (
            echo USE_MOCK_DATA=True> .env
        )
    )

    findstr /C:"USE_MOCK_DATA=True" .env >nul 2>&1
    if errorlevel 1 (
        echo USE_MOCK_DATA=True>> .env
    )

    echo.
    echo   ========================================================
    echo   Kurulum tamamlandi!
    echo   ========================================================
    echo.
) else (
    call .venv\Scripts\activate.bat
)

REM --- Paketi editable modda kur (kosulsuz, her acilista) ---
REM Kosullu calistirmak yanlisti: "import edilebiliyor mu" sorusu
REM "metadata guncel mi" sorusuna cevap vermiyor. Editable kurulumda paket
REM bir kez kurulunca hep import edilebilir, ama pyproject.toml degisince
REM (yeni entry point, yeni extra, yeni paket bulma kurali) yenilenmez.
REM --no-deps oldugu icin idempotent ve hizli.
echo   Paket kuruluyor...
pip install -e . --no-deps >nul 2>&1
if errorlevel 1 (
    echo   [HATA] Paket kurulamadi.
    echo   Ayrinti icin: pip install -e . --no-deps
    pause
    exit /b 1
)

REM --- Onceki islemi temizle ---
REM Yalnizca dashboard portu: API sunucusu artik opsiyonel ve bu script
REM tarafindan baslatilmiyor.
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8501" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)

REM --- Dashboard baslat ---
echo   Dashboard baslatiliyor...
start /B "" cmd /c "call .venv\Scripts\activate.bat && python -m streamlit run src\defect_risk_analyzer\ui\app.py --server.port 8501 --server.headless true 2>&1 > data\dashboard.log"

timeout /t 3 /nobreak >nul

REM --- Tarayici ac ---
start http://localhost:8501

echo.
echo   ========================================================
echo   Uygulama hazir!
echo.
echo   Dashboard:  http://localhost:8501
echo.
echo   Jira webhook kullanacaksaniz opsiyonel API sunucusunu
echo   ayrica kurup baslatin:
echo     pip install -r requirements-webhook.txt
echo     python -m uvicorn defect_risk_analyzer.api:app --port 8000
echo.
echo   Bu pencereyi kapatmak uygulamayi durdurur.
echo   ========================================================
echo.

:wait
timeout /t 60 /nobreak >nul
goto wait
