@echo off
rem Runs every automatic test (reading files, checks, maths, Excel, macros, questions).
cd /d "%~dp0.."
python -m pytest tests -q -W ignore
echo.
pause
