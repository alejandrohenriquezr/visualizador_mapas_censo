@echo off
setlocal
cd /d "%~dp0.."
python scripts\validate_repo.py . || exit /b 1
if not exist .git git init
git branch -M main
git add .
git status

echo.
echo Revise git status. Si esta correcto:
echo   git commit -m "Arquitectura inicial del visor censal"
echo Luego agregue el remoto de GitHub y haga push.
endlocal
