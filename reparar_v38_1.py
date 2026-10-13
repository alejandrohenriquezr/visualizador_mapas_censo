# -*- coding: utf-8 -*-
"""Reparación V38.1 para el Visor Censo 2024.

Se aplica SOBRE una instalación V38 que alcanzó la etapa de verificaciones.
Corrige la movilidad laboral regional y evita que cachés antiguas oculten
las correcciones de movilidad y pirámide.

No ejecuta git add, commit ni push.
"""

from pathlib import Path
import datetime as dt
import re
import shutil
import subprocess
import sys


def leer(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def guardar(path: Path, contenido: str) -> None:
    path.write_text(contenido, encoding="utf-8", newline="\n")


def respaldo(path: Path) -> Path:
    sello = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = path.with_name(f"{path.name}.v38_1_{sello}.bak")
    shutil.copy2(path, destino)
    return destino


def quitar_bloque(contenido: str, inicio: str, fin: str) -> str:
    # Elimina todas las redefiniciones antiguas delimitadas por marcadores.
    while inicio in contenido:
        i = contenido.index(inicio)
        j = contenido.find(fin, i)
        if j < 0:
            raise RuntimeError(f"Bloque incompleto: {inicio}")
        j += len(fin)
        contenido = contenido[:i].rstrip() + "\n\n" + contenido[j:].lstrip("\n")
    return contenido


def reparar_movilidad(path: Path) -> bool:
    contenido = leer(path)
    original = contenido

    # V37/V38 agregaban una segunda definición al final del módulo. V38.1 la
    # elimina y deja la regla regional dentro de la función canónica.
    contenido = quitar_bloque(
        contenido,
        "# BEGIN V38 MOVILIDAD LABORAL REGIONAL",
        "# END V38 MOVILIDAD LABORAL REGIONAL",
    )
    contenido = quitar_bloque(
        contenido,
        "# BEGIN V37 MOVILIDAD LABORAL REGIONAL",
        "# END V37 MOVILIDAD LABORAL REGIONAL",
    )

    if "# BEGIN V38.1 MOVILIDAD REGIONAL CANONICA" not in contenido:
        cabecera = (
            "def resolver_movilidad_laboral_fase3(consulta: str):\n"
            "    q = _norm(consulta)\n"
        )
        if contenido.count(cabecera) != 1:
            raise RuntimeError(
                "No se encontró una única función canónica "
                "resolver_movilidad_laboral_fase3()."
            )

        regla = '''def resolver_movilidad_laboral_fase3(consulta: str):
    q = _norm(consulta)

    # BEGIN V38.1 MOVILIDAD REGIONAL CANONICA
    # Una consulta «movilidad laboral por región» se interpreta como matriz
    # origen-destino entre región de residencia y región de trabajo.
    es_regional = bool(
        re.search(r"\\bmovilidad\\s+laboral\\s+por\\s+regiones?\\b", q)
        or re.search(r"\\bmovilidad\\s+laboral\\s+entre\\s+regiones?\\b", q)
        or re.search(
            r"\\bmatriz\\b.*\\bmovilidad\\s+laboral\\b.*\\bregiones?\\b",
            q,
        )
    )
    if es_regional:
        salida = _base_f3(IND_MATRIZ, consulta)
        incluir_diagonal = bool(
            re.search(
                r"\\b(?:incluir|incluyendo|con)\\s+(?:la\\s+)?"
                r"(?:misma\\s+region|diagonal)\\b",
                q,
            )
        )
        if re.search(
            r"\\b(?:sin|no\\s+incluir|excluir|excluyendo)\\s+(?:la\\s+)?"
            r"(?:misma\\s+region|diagonal)\\b|"
            r"\\bregiones?\\s+distintas?\\b|"
            r"\\binterregionales?\\b",
            q,
        ):
            incluir_diagonal = False

        salida.update({
            "movilidad_nivel": "region",
            "nivel_geografico": "region",
            "movilidad_incluir_diagonal": incluir_diagonal,
            "_origen_interpretacion": (
                "movilidad_laboral_fase3_regional_v381"
            ),
            "nota_interpretacion": (
                "Universo: personas ocupadas con un único lugar de trabajo "
                "territorialmente identificable en Chile. La región de "
                "residencia actual es el origen y la región de trabajo es el "
                "destino. P44=1/2 se asigna a la misma región de residencia; "
                "P44=3 usa la región derivada del código comunal específico "
                "de trabajo. Se excluyen otro país, varias comunas o países, "
                "No respuesta y No aplica."
            ),
        })
        return salida
    # END V38.1 MOVILIDAD REGIONAL CANONICA
'''
        contenido = contenido.replace(cabecera, regla, 1)

    definiciones = contenido.count(
        "def resolver_movilidad_laboral_fase3(consulta: str):"
    )
    if definiciones != 1:
        raise RuntimeError(
            f"Después de reparar movilidad quedaron {definiciones} definiciones."
        )

    if contenido == original:
        return False
    respaldo(path)
    guardar(path, contenido.rstrip() + "\n")
    return True


def reparar_nl_parser(path: Path) -> bool:
    contenido = leer(path)
    original = contenido
    viejo = 'intencion["nivel_geografico"] = "comuna"'
    nuevo = (
        'intencion["nivel_geografico"] = '
        'intencion.get("movilidad_nivel") or "comuna"'
    )
    if nuevo not in contenido:
        if contenido.count(viejo) != 1:
            raise RuntimeError(
                "No se encontró de forma única el nivel geográfico de movilidad."
            )
        contenido = contenido.replace(viejo, nuevo, 1)
    if contenido == original:
        return False
    respaldo(path)
    guardar(path, contenido)
    return True


def reparar_cache_main(path: Path) -> bool:
    contenido = leer(path)
    original = contenido

    # Una respuesta aprobada anterior puede impedir que la nueva lógica se ejecute.
    if "# BEGIN V38.1 INVALIDACION CACHE" not in contenido:
        ancla = (
            '    if "sexo" in q and "edad" in q and not '
            '(respuesta or {}).get("piramide"):\n'
            '        return True\n'
        )
        if ancla not in contenido:
            raise RuntimeError(
                "No se encontró el bloque de invalidación de caché V33."
            )
        extra = ancla + '''    # BEGIN V38.1 INVALIDACION CACHE
    # Distribuciones de edad guardadas antes de V38 no tienen la tabla auxiliar
    # edad × sexo necesaria para la pirámide.
    if (
        (respuesta or {}).get("tipo_visualizacion") == "tortas_mapa"
        and str(interp.get("variable") or "") in {"edad", "edad_quinquenal"}
        and not (respuesta or {}).get("piramide")
    ):
        return True

    # Una caché antigua de movilidad regional puede contener una interpretación
    # genérica equivocada (por ejemplo una variable P32 de discapacidad).
    if re.search(r"\\bmovilidad\\s+laboral\\s+por\\s+regiones?\\b", q):
        tipo = str(interp.get("tipo_consulta") or "")
        if (
            not tipo.startswith("movilidad_laboral")
            or (respuesta or {}).get("tipo_visualizacion") != "matriz_od"
            or (respuesta or {}).get("nivel_geografico") != "region"
        ):
            return True
    # END V38.1 INVALIDACION CACHE
'''
        contenido = contenido.replace(ancla, extra, 1)

    # Expone el nivel especializado en el diagnóstico de interpretación.
    campo = '            "movilidad_nivel": intencion.get("movilidad_nivel"),\n'
    if campo not in contenido:
        ancla = '            "movilidad_metrica": intencion.get("movilidad_metrica"),\n'
        if ancla not in contenido:
            raise RuntimeError("No se encontró movilidad_metrica en main.py.")
        contenido = contenido.replace(ancla, ancla + campo, 1)

    if contenido == original:
        return False
    respaldo(path)
    guardar(path, contenido)
    return True


def verificar_v38_base(root: Path) -> None:
    # La reparación está diseñada para la copia en la que V38 ya fue aplicado.
    requisitos = {
        root / "backend" / "data_engine.py": "edad_sexo_auxiliar_v38",
        root / "backend" / "main.py": "BEGIN V38 CANCELACION ESC",
        root / "backend" / "state_store.py": "BEGIN V38 APRENDIZAJE CANCELACION",
        root / "frontend" / "index.html": "v38-esc-y-piramide-simple",
    }
    faltan = []
    for path, marca in requisitos.items():
        if not path.exists() or marca not in leer(path):
            faltan.append(f"{path}: {marca}")
    if faltan:
        raise RuntimeError(
            "V38 no está completamente aplicado. Faltan estas marcas:\n- "
            + "\n- ".join(faltan)
        )


def main() -> None:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
    verificar_v38_base(root)

    cambios = []
    if reparar_movilidad(root / "backend" / "labor_mobility_resolver.py"):
        cambios.append("backend/labor_mobility_resolver.py")
    if reparar_nl_parser(root / "backend" / "nl_parser.py"):
        cambios.append("backend/nl_parser.py")
    if reparar_cache_main(root / "backend" / "main.py"):
        cambios.append("backend/main.py")

    # Validación de sintaxis tras la reparación.
    for path in [
        root / "backend" / "labor_mobility_resolver.py",
        root / "backend" / "nl_parser.py",
        root / "backend" / "main.py",
    ]:
        subprocess.run(
            [sys.executable, "-m", "py_compile", str(path)],
            check=True,
        )

    print("V38.1 aplicado correctamente.")
    if cambios:
        print("Archivos reparados:")
        for cambio in cambios:
            print(" -", cambio)
    else:
        print("Los cambios V38.1 ya estaban presentes.")
    print("Sintaxis Python: OK")
    print("GitHub no fue modificado.")


if __name__ == "__main__":
    main()
