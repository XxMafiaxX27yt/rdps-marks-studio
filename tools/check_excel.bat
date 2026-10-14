@echo off
rem Opens a test workbook in real Excel, recalculates every formula and compares with Python, then runs the macros.
cd /d "%~dp0.."
python tools\excel_check.py
pause
