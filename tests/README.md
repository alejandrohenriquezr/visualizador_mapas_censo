# Pruebas

Las pruebas históricas del backend se consolidan aquí. Para ejecutarlas localmente:

```cmd
set PYTHONPATH=backend
python -m unittest discover -s tests\backend -p "test_*.py"
```

Algunas pruebas requieren microdatos locales y no se ejecutan en CI público.
