@echo off
setlocal
cd /d "%~dp0.."
python scripts\health.py
if errorlevel 1 exit /b %errorlevel%
