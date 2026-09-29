@echo off
setlocal
cd /d "%~dp0.."
for /f "tokens=1,* delims==" %%A in ('findstr /b "OLLAMA_MODEL=" .env') do set MODEL=%%B
if not defined MODEL set MODEL=qwen2.5:3b-instruct
docker compose up -d llm
docker compose exec llm ollama pull %MODEL%
endlocal
