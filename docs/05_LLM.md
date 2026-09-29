# Tratamiento del LLM

Ollama corre como servicio interno `llm`. Backend usa `OLLAMA_URL=http://llm:11434/api/generate` y el modelo definido en `OLLAMA_MODEL`.

El LLM se utiliza para interpretar lenguaje natural cuando no existe una resolución determinista suficientemente específica. No recibe la responsabilidad del cálculo; el cálculo se ejecuta mediante reglas validadas y DuckDB.

El modelo se descarga una sola vez con `scripts/PULL_LLM.cmd` y queda persistido en el volumen Docker `visor_censo_ollama`.
