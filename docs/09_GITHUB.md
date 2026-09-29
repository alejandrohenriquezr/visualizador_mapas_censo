# Preparación para GitHub

Antes de subir:

```cmd
python scripts\validate_repo.py .
scripts\INICIALIZAR_GIT.cmd
```

Revise `git status`. Deben quedar fuera `.env`, Parquet, FileGDB, SQLite, respaldos y runtime.

Después:

```cmd
git commit -m "Arquitectura inicial del visor censal"
git remote add origin https://github.com/ORGANIZACION/REPOSITORIO.git
git push -u origin main
```

El workflow `ci.yml` valida estructura, compila Python y construye las tres imágenes propias sin requerir microdatos.
