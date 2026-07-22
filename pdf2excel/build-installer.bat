@echo off
rem ============================================================
rem  build-installer.bat - bangun PDF-ke-Excel-Setup.exe
rem  Cukup dobel-klik file ini di PC Windows.
rem
rem  Prasyarat (pasang sekali saja):
rem   1. Python 3.11+  - https://www.python.org/downloads/
rem      (centang "Add Python to PATH" saat instalasi!)
rem   2. Inno Setup 6  - https://jrsoftware.org/isdl.php
rem ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo === [1/6] Memeriksa Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo GAGAL: Python tidak ditemukan.
    echo Pasang dari https://www.python.org/downloads/ dan centang
    echo "Add Python to PATH", lalu jalankan file ini lagi.
    pause
    exit /b 1
)
python --version

echo.
echo === [2/6] Memeriksa Inno Setup...
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo GAGAL: Inno Setup 6 tidak ditemukan.
    echo Pasang dari https://jrsoftware.org/isdl.php lalu jalankan
    echo file ini lagi.
    pause
    exit /b 1
)
echo Inno Setup: "%ISCC%"

echo.
echo === [3/6] Menyiapkan lingkungan Python (hanya lama saat pertama kali)...
if not exist .venv (
    python -m venv .venv || goto :fail
)
call .venv\Scripts\activate.bat || goto :fail
python -m pip install --quiet --upgrade pip || goto :fail
pip install --quiet -r requirements.txt pyinstaller || goto :fail

echo.
echo === [4/6] Membekukan aplikasi (PyInstaller)...
pyinstaller pdf2excel.spec --noconfirm || goto :fail

echo.
echo === [5/6] Menguji hasil beku dengan OCR sungguhan...
python samples\make_sample.py sample-uji.pdf || goto :fail
dist\pdf2excel\pdf2excel-cli.exe convert sample-uji.pdf -o sample-uji.xlsx --no-session || goto :fail
if not exist sample-uji.xlsx goto :fail
del sample-uji.pdf sample-uji.xlsx >nul 2>&1
echo Uji OCR lulus.

echo.
echo === [6/6] Membungkus installer (Inno Setup)...
python installer\gen_version.py || goto :fail
"%ISCC%" installer\setup.iss || goto :fail
python installer\gen_sbom.py installer\Output\PDF-ke-Excel-Setup.exe || goto :fail

echo.
echo ============================================================
echo  SELESAI!
echo  Installer siap dibagikan:
echo    %cd%\installer\Output\PDF-ke-Excel-Setup.exe
echo ============================================================
pause
exit /b 0

:fail
echo.
echo GAGAL. Baca pesan kesalahan di atas. Kalau bingung, kirimkan
echo tangkapan layar jendela ini ke pendamping teknis.
pause
exit /b 1
