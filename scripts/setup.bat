@echo off
chcp 65001 >nul 2>&1
echo ============================================================
echo   Defect Risk Analyzer - Ilk Kurulum
echo ============================================================
echo.

:: Check Python
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [HATA] Python bulunamadi. Python 3.11+ yukleyin: https://python.org
    echo.
    pause
    exit /b 1
)

echo [1/4] Python bulundu:
python --version
echo.

:: Create virtual environment
if not exist ".venv" (
    echo [2/4] Sanal ortam olusturuluyor...
    python -m venv .venv
    if %ERRORLEVEL% NEQ 0 (
        echo [HATA] Sanal ortam olusturulamadi.
        pause
        exit /b 1
    )
    echo       Sanal ortam olusturuldu.
) else (
    echo [2/4] Sanal ortam zaten mevcut, atlaniyor.
)
echo.

:: Install dependencies
echo [3/4] Bagimliliklar yukleniyor...
call .venv\Scripts\activate.bat
pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo [HATA] Bagimliliklar yuklenemedi.
    pause
    exit /b 1
)
echo       Bagimliliklar yuklendi.
echo.

:: Prepare data directory and .env
echo [4/4] Yapilandirma hazirlaniyor...
if not exist "data" mkdir data

if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo       .env dosyasi olusturuldu. Lutfen duzenleyin veya mock modu kullanin.
    ) else (
        echo       [UYARI] .env.example bulunamadi. .env dosyasini manuel olusturun.
    )
) else (
    echo       .env dosyasi zaten mevcut, atlaniyor.
)
echo.

echo ============================================================
echo   Kurulum tamamlandi!
echo.
echo   Sonraki adimlar:
echo     1. .env dosyasini duzenleyin (veya USE_MOCK_DATA=True yapin)
echo     2. scripts\start.bat ile uygulamayi baslatin
echo ============================================================
echo.
pause
