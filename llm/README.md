# LLM

El servicio `llm` usa la imagen oficial de Ollama. El modelo no se versiona; se guarda en el volumen `visor_censo_ollama`.

Después del primer `docker compose up -d llm`, ejecute:

```cmd
scripts\PULL_LLM.cmd
```
