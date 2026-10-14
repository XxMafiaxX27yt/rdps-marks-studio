@echo off
rem Copies the latest code and libraries into the web folder (run after changing anything in core\).
cd /d "%~dp0.."
python tools\build_web.py
pause
