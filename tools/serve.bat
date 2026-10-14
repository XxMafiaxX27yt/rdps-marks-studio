@echo off
rem Starts the website on this laptop for testing and opens it in the browser.
cd /d "%~dp0.."
start "" http://localhost:8765
python tools\serve.py 8765
