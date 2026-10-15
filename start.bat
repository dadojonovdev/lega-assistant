@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\pip install -r requirements-pc.txt
)
if not exist .env (
  echo Создай файл .env по образцу .env.pc.example и запусти снова.
  pause
  exit /b 1
)
:loop
.venv\Scripts\python bot.py
echo Бот остановился, перезапуск через 10 секунд. Закрой окно, чтобы выйти.
timeout /t 10 >nul
goto loop
