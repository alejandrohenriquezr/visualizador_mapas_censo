@echo off
cd /d "%~dp0.."
for /f "tokens=1,* delims==" %%A in ('findstr /b "VISOR_PORT=" .env') do set PORT=%%B
if not defined PORT set PORT=8010
python scripts\smoke_test.py http://localhost:%PORT%
