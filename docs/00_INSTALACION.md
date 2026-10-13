# Instalación y requisitos

Esta guía permite reproducir una instalación desde una copia limpia del repositorio. El código y la configuración están en Git; los archivos censales se descargan por separado porque son voluminosos y pertenecen a los portales oficiales.

## 1. Instalar Docker

### Windows

Instala [Docker Desktop para Windows](https://docs.docker.com/desktop/setup/install/windows-install/), inicia Docker Desktop y espera a que el motor esté listo. Docker Desktop puede requerir WSL 2, virtualización activada y aceptación de sus términos. En organizaciones, comprueba la licencia de Docker Desktop aplicable a tu institución.

No es necesario instalar Python, GDAL ni Ollama en Windows para ejecutar el sitio. Python sólo se necesita si quieres correr las herramientas de validación y benchmarks desde el host. GDAL está dentro de la imagen cartográfica; Ollama corre dentro del servicio Docker `llm`.

### Linux

Instala Docker Engine y el complemento Compose v2 siguiendo la [documentación oficial para Linux](https://docs.docker.com/engine/install/) y [Compose](https://docs.docker.com/compose/install/linux/). Ejecuta Docker con una cuenta que tenga permisos para acceder al daemon.

## 2. Descargar los microdatos censales

Abre la [página oficial de resultados del Censo 2024 del INE](https://censo2024.ine.gob.cl/resultados/) y descarga la base de microdatos en formato Parquet (personas, hogares y viviendas). Usa los datos oficiales más recientes disponibles y respeta las condiciones de uso indicadas por el INE.

Extrae los archivos Parquet directamente en la carpeta `datos/` del proyecto. El backend espera exactamente estos nombres:

- `datos/personas_censo2024.parquet`
- `datos/hogares_censo2024.parquet`
- `datos/viviendas_censo2024.parquet`

Si el paquete descargado usa otros nombres, renómbralos conservando la correspondencia entre tabla y archivo. No subas los microdatos a GitHub.

## 3. Descargar la cartografía

El INE publicó las bases a nivel de manzana y la cartografía en su [aviso oficial del Censo 2024](https://censo2024.ine.gob.cl/ine-publica-bases-de-datos-a-nivel-de-manzana-y-cartografia-del-censo-de-poblacion-y-vivienda-2024/). Consulta también [Geodatos Abiertos del INE](https://www.ine.gob.cl/herramientas/portal-de-mapas/geodatos-abiertos/2024/03/12/informaci%C3%B3n-censo-2024), donde la sección de documentos y descargas mantiene las capas cartográficas. Descarga la File Geodatabase correspondiente a la cartografía censal nacional.

Extrae la carpeta completa de FileGDB (incluyendo todos sus archivos internos) directamente dentro de `cartografia/`, de modo que exista:

```text
cartografia/Cartografia_censo2024_Pais.gdb/
```

Si el portal entrega un nombre distinto, puedes conservarlo y ajustar `CENSO_CARTOGRAFIA_GDB` en `.env` usando la ruta **dentro del contenedor**, por ejemplo `/app/cartografia/OTRO_NOMBRE.gdb`. El instalador de Windows comprueba esa ruta dentro de `cartografia/\`; la carpeta del host se configura con `CENSO_CARTOGRAFIA_HOST`.

No subas la FileGDB a GitHub.

## 4. Configurar e instalar el visor en Windows

Desde la carpeta raíz del repositorio ejecuta:

```cmd
INSTALAR.cmd
```

La primera ejecución crea `.env` a partir de `.env.example` y lo abre en el Bloc de notas. Cambia `POSTGRES_PASSWORD` por una clave alfanumérica propia (para que la URL de conexión de PostgreSQL no se rompa), guarda el archivo y vuelve a ejecutar el instalador. El instalador verifica Docker, los tres Parquet y la FileGDB; luego crea volúmenes persistentes, inicia PostgreSQL, cartografía y Ollama, descarga el modelo indicado por `OLLAMA_MODEL`, construye backend/frontend y comprueba `/healthz`.

La primera instalación puede tardar: Docker descarga imágenes, compila servicios, procesa geometrías y descarga el modelo. Requiere conexión a Internet. El instalador no acepta términos de terceros por ti ni descarga silenciosamente paquetes de datos oficiales.

Al finalizar, abre `http://localhost:8010`. Para otro puerto, cambia `VISOR_PORT` en `.env`.

## 5. Instalación manual o Linux

Crea y configura `.env`:

```sh
cp .env.example .env
```

Cambia `POSTGRES_PASSWORD` y asegúrate de tener los datos en las rutas configuradas. Luego, desde la raíz:

```sh
docker compose config -q
docker volume create visor_censo_postgres
docker volume create visor_censo_ollama
docker volume create visor_censo_cartography_cache
docker compose up -d db llm cartography
docker compose exec -T llm ollama pull qwen2.5:3b-instruct
docker compose up -d --build backend frontend
docker compose ps
```

Si cambiaste `OLLAMA_MODEL`, usa ese mismo nombre en el comando `ollama pull`. Para verificar el sitio, abre `http://localhost:8010/healthz`.

## Qué se descarga automáticamente

| Recurso | Cómo se obtiene |
| --- | --- |
| Docker Desktop / Engine | Instalación explícita siguiendo el portal oficial. |
| Microdatos y FileGDB | Descarga manual desde los portales oficiales del INE; no se incorporan a Git. |
| Imágenes de servicios | Docker Compose las descarga y construye al instalar. |
| Ollama y el modelo | Ollama corre en el servicio `llm`; el instalador inicia el contenedor y descarga el modelo configurado. No se instala Ollama como aplicación de Windows. |
| Python y GDAL | No se requieren en el host para ejecutar el visor; las dependencias viven en los contenedores. |
