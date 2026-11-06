@echo off
chcp 65001 >nul
cd /d "%~dp0"
start "" pythonw app.py
if errorlevel 1 (
    python app.py
)
