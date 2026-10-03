@echo off
chcp 65001 >nul
title Turk tili speaking test bot
cd /d "%~dp0"

echo ========================================================
echo    TURK TILI SPEAKING TEST BOT - ishga tushirish
echo ========================================================
echo.

rem --- 1. .env fayl bormi ---
if not exist ".env" (
    echo [XATO] .env fayl topilmadi.
    echo        .env faylni shu papkaga qo'ying: %cd%
    echo.
    pause
    exit /b 1
)

rem --- 2. Yangi kodni olish (git bo'lsa; xato bo'lsa davom etadi) ---
where git >nul 2>nul
if not errorlevel 1 (
    echo [1/4] Yangilanishlar tekshirilmoqda...
    git pull --ff-only
    if errorlevel 1 echo        Yangilab bo'lmadi - mavjud kod bilan davom etiladi.
) else (
    echo [1/4] git topilmadi - yangilash o'tkazib yuborildi.
)
echo.

rem --- 3. Python virtual muhit (venv) ---
if not exist "venv\Scripts\python.exe" (
    echo [2/4] Virtual muhit yaratilmoqda...
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -m venv venv
    ) else (
        python -m venv venv
    )
    if not exist "venv\Scripts\python.exe" (
        echo [XATO] Python topilmadi. https://www.python.org dan o'rnating
        echo        va o'rnatishda "Add Python to PATH" ni belgilang.
        pause
        exit /b 1
    )
) else (
    echo [2/4] Virtual muhit tayyor.
)
echo.

rem --- 4. Kutubxonalar (requirements.txt o'zgargan bo'lsa qayta o'rnatiladi) ---
fc /b requirements.txt venv\requirements.installed >nul 2>nul
if errorlevel 1 (
    echo [3/4] Kutubxonalar o'rnatilmoqda - birinchi marta bir necha daqiqa olishi mumkin...
    venv\Scripts\python.exe -m pip install --upgrade pip >nul
    venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [XATO] Kutubxonalarni o'rnatib bo'lmadi. Internetni tekshiring.
        pause
        exit /b 1
    )
    copy /y requirements.txt venv\requirements.installed >nul
) else (
    echo [3/4] Kutubxonalar o'rnatilgan.
)
echo.

rem --- 5. Botni ishga tushirish; yiqilsa 5 soniyadan keyin qayta ishga tushadi ---
echo [4/4] Bot ishga tushmoqda. To'xtatish uchun shu oynani yoping.
echo.
:run
venv\Scripts\python.exe run.py
echo.
echo [!] Bot to'xtadi. 5 soniyadan keyin qayta ishga tushadi...
echo     (Butunlay to'xtatish uchun shu oynani yoping.)
timeout /t 5 /nobreak >nul
goto run
