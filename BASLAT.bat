@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo.
echo   ========================================================
echo   🔍  Defect Risk Analyzer
echo   ========================================================
echo.

:: ---------------------------------------------------------------
:: 1. Python kontrolu
:: ---------------------------------------------------------------
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
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

:: ---------------------------------------------------------------
:: 2. Ilk calistirma: sanal ortam + bagimliliklar
:: ---------------------------------------------------------------
if not exist ".venv\Scripts\activate.bat" (
    echo   Ilk calistirma tespit edildi - kurulum basliyor...
    echo   (Bu islem sadece bir kez yapilir, 1-2 dakika surebilir)
    echo.

    echo   [1/4] Sanal ortam olusturuluyor...
    python -m venv .venv
    if %ERRORLEVEL% NEQ 0 (
        echo   [HATA] Sanal ortam olusturulamadi.
        pause
        exit /b 1
    )

    call .venv\Scripts\activate.bat

    echo   [2/4] Bagimliliklar yukleniyor...
    pip install --upgrade pip >nul 2>&1
    pip install -r requirements.txt
    if %ERRORLEVEL% NEQ 0 (
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

    :: Ilk kullanımda mock modu aktif olsun
    findstr /C:"USE_MOCK_DATA=True" .env >nul 2>&1
    if %ERRORLEVEL% NEQ 0 (
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

:: ---------------------------------------------------------------
:: 3. Onceki islemleri temizle (port cakismasini onle)
:: ---------------------------------------------------------------
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8501" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)

:: ---------------------------------------------------------------
:: 4. API sunucusunu baslat
:: ---------------------------------------------------------------
echo   API sunucusu baslatiliyor...
start /B "" cmd /c "call .venv\Scripts\activate.bat && python -m uvicorn api:app --host 0.0.0.0 --port 8000 2>&1 > data\api.log"

:: API'nin hazir olmasini bekle
echo   API hazir olana kadar bekleniyor...
timeout /t 4 /nobreak >nul

:: ---------------------------------------------------------------
:: 5. Dashboard'u baslat
:: ---------------------------------------------------------------
echo   Dashboard baslatiliyor...
start /B "" cmd /c "call .venv\Scripts\activate.bat && python -m streamlit run dashboard.py --server.port 8501 --server.headless true 2>&1 > data\dashboard.log"

timeout /t 3 /nobreak >nul

:: ---------------------------------------------------------------
:: 6. Tarayici ac
:: ---------------------------------------------------------------
start http://localhost:8501

echo.
echo   ========================================================
echo   Uygulama hazir!
echo.
echo   Dashboard:  http://localhost:8501
echo   API:        http://localhost:8000
echo.
echo   Bu pencereyi kapatmak uygulamayi durdurur.
echo   ========================================================
echo.
echo   Kapatmak icin CTRL+C basin veya bu pencereyi kapatin.

:: Pencere acik kalsin — kapaninca islemler de kapanir
:wait
timeout /t 60 /nobreak >nul
goto wait
