@echo off
rem One-time setup for the developer laptop: installs the Python tools used for tests and building.
rem (Teachers never need this - they just open the website.)
cd /d "%~dp0.."
echo Installing Python packages...
python -m pip install -r requirements-dev.txt
echo.
echo Done. You can now double-click run_tests.bat, serve.bat or build_web.bat.
pause
