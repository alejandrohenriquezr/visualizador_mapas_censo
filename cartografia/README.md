# Cartografía

Esta carpeta no se versiona. Descarga la File Geodatabase censal desde los [Geodatos Abiertos del INE](https://www.ine.gob.cl/herramientas/portal-de-mapas/geodatos-abiertos/2024/03/12/informaci%C3%B3n-censo-2024) o consulta el [aviso oficial de cartografía del Censo 2024](https://censo2024.ine.gob.cl/ine-publica-bases-de-datos-a-nivel-de-manzana-y-cartografia-del-censo-de-poblacion-y-vivienda-2024/).

Extrae la carpeta completa directamente aquí. El nombre esperado es:

```text
cartografia/Cartografia_censo2024_Pais.gdb/
```

La carpeta `.gdb` contiene varios archivos internos: conserva todos. Si usas otro nombre, cambia `CENSO_CARTOGRAFIA_GDB` en `.env` por la ruta del contenedor, por ejemplo `/app/cartografia/OTRO_NOMBRE.gdb`.

La cartografía no se sube a GitHub. Consulta [Instalación y requisitos](../docs/00_INSTALACION.md) para el procedimiento completo.
