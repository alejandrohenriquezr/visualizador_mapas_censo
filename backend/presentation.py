# -*- coding: utf-8 -*-
"""Redacción natural de títulos y leyendas del visor."""
import re

from dictionary import VARIABLES

def _nombre_territorio(nivel, codigo):
    lugares = VARIABLES.get("geografia", {}).get(nivel, {})
    return next((v for k, v in lugares.items()
                 if str(k).isdigit() and str(codigo).isdigit()
                 and int(k) == int(codigo)), str(codigo))


def _descripcion_variable(tabla, variable):
    info = VARIABLES[tabla]["variables"][variable]
    texto = str(info.get("descripcion") or variable).strip()
    texto = re.sub(r"^\s*\d+(?:\.\d+)?[a-z]?\.\s*", "", texto, flags=re.I)
    return texto.strip(" ¿?\t\n")


def _frase_geografica(intencion):
    """Redacta la desagregación/filtro territorial sin etiquetas técnicas."""
    nivel = intencion.get("nivel_geografico") or "region"
    plan = intencion.get("plan_cruce") or {}
    selecciones = plan.get("selecciones_geograficas") or []
    if selecciones:
        sel = selecciones[0]
        nivel_sel = sel.get("nivel")
        nombres = [_nombre_territorio(nivel_sel, c) for c in sel.get("codigos") or []]
        if nombres:
            plural = {"region": "regiones", "provincia": "provincias", "comuna": "comunas"}.get(nivel_sel, nivel_sel)
            lista = ", ".join(nombres[:-1]) + (" y " + nombres[-1] if len(nombres) > 1 else nombres[-1])
            if nivel == "comuna" and nivel_sel == "region":
                return f"según comunas de las regiones de {lista}"
            if nivel == "provincia" and nivel_sel == "region":
                return f"según provincias de las regiones de {lista}"
            return f"según {nivel}s en las {plural} de {lista}"
    filtro = intencion.get("filtro_geografico_nivel")
    codigo = intencion.get("filtro_geografico_codigo")
    nombre = _nombre_territorio(filtro, codigo) if filtro and codigo is not None else None

    if filtro == "comuna" and nombre:
        return f"en la comuna de {nombre}"
    if nivel == "comuna":
        if filtro == "region" and nombre:
            return f"según comunas de la región de {nombre}"
        if filtro == "provincia" and nombre:
            return f"según comunas de la provincia de {nombre}"
        return "según comunas"
    if nivel == "provincia":
        if filtro == "region" and nombre:
            return f"según provincias de la región de {nombre}"
        if filtro == "provincia" and nombre:
            return f"en la provincia de {nombre}"
        return "según provincias"
    if filtro == "region" and nombre:
        return f"en la región de {nombre}"
    return "según regiones"


def _etiqueta_filtro(filtro):
    tabla, variable = filtro.get("tabla"), filtro.get("variable")
    if not tabla or not variable or tabla not in VARIABLES:
        return str(filtro.get("etiqueta") or "").strip()
    info = VARIABLES[tabla]["variables"].get(variable, {})
    etiqueta = filtro.get("etiqueta")
    if not etiqueta and filtro.get("valores"):
        etiqueta = " / ".join(
            str(info.get("categorias", {}).get(str(v), v))
            for v in filtro.get("valores", [])
        )
    return str(etiqueta or "").strip()


def _frase_filtro(filtro, objetivo="personas"):
    tabla, variable = filtro.get("tabla"), filtro.get("variable")
    tipo = filtro.get("tipo")

    if tipo in {"existe_en_hogar", "no_existe_en_hogar", "conteo_relacionado"}:
        return str(filtro.get("etiqueta") or "con la condición jerárquica indicada").strip()

    if tipo == "rango":
        minimo, maximo = filtro.get("minimo"), filtro.get("maximo")
        inc_min = filtro.get("incluir_minimo", True)
        inc_max = filtro.get("incluir_maximo", True)
        if variable == "edad":
            if minimo is not None and maximo is not None:
                return f"entre {minimo:g} y {maximo:g} años"
            if minimo is not None:
                return (f"de {minimo:g} años o más" if inc_min
                        else f"mayores de {minimo:g} años")
            if maximo is not None:
                return (f"de {maximo:g} años o menos" if inc_max
                        else f"menores de {maximo:g} años")
        if variable == "escolaridad":
            if minimo is not None and maximo is not None:
                return f"con entre {minimo:g} y {maximo:g} años de escolaridad"
            if minimo is not None:
                return (f"con {minimo:g} años o más de escolaridad" if inc_min
                        else f"con más de {minimo:g} años de escolaridad")
            if maximo is not None:
                return (f"con {maximo:g} años o menos de escolaridad" if inc_max
                        else f"con menos de {maximo:g} años de escolaridad")
        if variable == "p46a_tot_hijs_nac" and minimo == 0 and not inc_min and maximo is None:
            return "que han tenido al menos una hija o hijo nacido vivo"
        desc = _descripcion_variable(tabla, variable) if tabla and variable else variable
        return f"con {desc.lower()} en el rango solicitado"

    if tipo != "categoria":
        return str(filtro.get("etiqueta") or "").strip()

    etiqueta = _etiqueta_filtro(filtro)
    etiqueta_limpia = re.sub(r"^(?:sí|si)\s*,?\s*", "", etiqueta, flags=re.I).strip()

    if variable == "parentesco":
        return f"cuyo parentesco con la jefa o jefe de hogar es {etiqueta}"
    if variable == "p23_est_civil":
        return f"cuyo estado conyugal o civil es {etiqueta}"
    if variable == "sexo":
        if etiqueta.lower().startswith("hombre"):
            return "hombres"
        if etiqueta.lower().startswith("mujer"):
            return "mujeres"
    if variable == "discapacidad":
        return "con discapacidad" if "con discapacidad" in etiqueta.lower() else "sin discapacidad"

    p32 = {
        "p32a_dificultad_ver": "para ver aun usando anteojos o lentes",
        "p32b_dificultad_oir": "para oír aun usando audífono",
        "p32c_dificultad_mover": "para caminar o subir escaleras",
        "p32d_dificultad_cogni": "para recordar o concentrarse",
        "p32e_dificultad_cuidado": "para realizar tareas de cuidado personal",
        "p32f_dificultad_comunic": "para comunicarse",
    }
    if variable in p32:
        if etiqueta_limpia.lower() == "no puede hacerlo":
            return f"que no pueden hacerlo {p32[variable]}"
        return f"con {etiqueta_limpia.lower()} {p32[variable]}"

    if variable == "tipologia_hogar":
        if "unipersonal" in etiqueta.lower():
            return "que viven en hogares unipersonales"
        return f"que viven en hogares de tipología {etiqueta}"
    if variable == "p2_tipo_vivienda":
        if objetivo == "personas":
            if etiqueta.lower().startswith("departamento"):
                return "que viven en departamentos"
            if etiqueta.lower().startswith("casa"):
                return "que viven en casas"
        return f"con tipo de vivienda {etiqueta}"
    if variable == "p27_nacionalidad_esp":
        return f"de nacionalidad {etiqueta}"
    if variable == "p25_lug_nacimiento_esp":
        return f"nacidas en {etiqueta}"
    if variable == "p24_lug_resid5_esp":
        return f"que residían en 2019 en {etiqueta}"
    if variable == "p44_lug_trab_esp":
        return f"cuyo lugar de trabajo está en {etiqueta}"

    desc = _descripcion_variable(tabla, variable)
    return f"con {desc[0].lower() + desc[1:] if desc else variable}: {etiqueta}"


def _unir_filtros(frases):
    frases = [f.strip() for f in frases if f and f.strip()]
    if not frases:
        return ""
    salida = frases[0]
    for frase in frases[1:]:
        if frase.startswith(("con ", "que ", "cuyo ", "entre ", "de ", "mayores ", "menores ")):
            salida += " " + frase
        else:
            salida += " y " + frase
    return salida


def _frase_ast(nodo, objetivo="personas"):
    if not isinstance(nodo, dict):
        return ""
    op = nodo.get("op")
    if op in {"and", "or"}:
        frases = [_frase_ast(x, objetivo) for x in nodo.get("args") or []]
        frases = [x for x in frases if x]
        if not frases:
            return ""
        if op == "and":
            return _unir_filtros(frases)
        return " o ".join(frases)
    if op == "not":
        frase = _frase_ast(nodo.get("arg"), objetivo)
        if not frase:
            return ""
        if frase.startswith("con "):
            return "sin " + frase[4:]
        return "no " + frase
    return _frase_filtro(nodo, objetivo)


def _frase_medida(plan):
    medida = plan.get("medida") or {}
    op = medida.get("operacion", "conteo_distinto")
    objetivo = plan.get("entidad_objetivo") or "personas"
    if op == "conteo_distinto":
        return None
    tabla, variable = medida.get("tabla"), medida.get("variable")
    etiquetas_medida = {
        ("personas", "edad"): "edad",
        ("personas", "escolaridad"): "años de escolaridad",
        ("personas", "p46a_tot_hijs_nac"): "hijas e hijos nacidos vivos",
        ("personas", "p47a_tot_hijs_sobrev"): "hijas e hijos sobrevivientes",
        ("viviendas", "p5_num_dormitorios"): "número de dormitorios",
        ("viviendas", "p11a_num_personas"): "personas residentes habitualmente",
        ("viviendas", "cant_per"): "personas censadas por vivienda",
        ("viviendas", "cant_hog"): "hogares censados por vivienda",
    }
    desc = etiquetas_medida.get((tabla, variable), _descripcion_variable(tabla, variable).lower() if tabla and variable else "valor")
    prefijos = {
        "promedio": "Promedio de", "mediana": "Mediana de",
        "suma": "Suma de", "minimo": "Mínimo de", "maximo": "Máximo de",
    }
    return f"{prefijos.get(op, op.capitalize())} {desc}"


def _descripcion_plan_natural(intencion):
    personalizada = str(intencion.get("descripcion_personalizada") or "").strip().rstrip(".")
    if personalizada:
        return f"{personalizada}, {_frase_geografica(intencion)}."
    plan = intencion.get("plan_cruce") or {}
    objetivo = plan.get("entidad_objetivo") or "personas"
    dimensiones = plan.get("dimensiones") or []
    version = int(plan.get("version", 1) or 1)

    if version >= 2 and plan.get("filtro_ast"):
        filtros_texto = _frase_ast(plan.get("filtro_ast"), objetivo)
    else:
        filtros = plan.get("filtros") or []
        filtros_ordenados = sorted(
            enumerate(filtros),
            key=lambda par: (
                0 if par[1].get("tipo") == "rango" and par[1].get("variable") in {"edad", "escolaridad"} else 1,
                par[0],
            ),
        )
        frases = [_frase_filtro(f, objetivo) for _, f in filtros_ordenados]
        filtros_texto = _unir_filtros(frases)

    medida_texto = _frase_medida(plan)
    porcentaje = plan.get("porcentaje")

    if medida_texto:
        base = medida_texto
        if filtros_texto:
            base += " " + filtros_texto
    elif porcentaje:
        base = f"Porcentaje de {objetivo}"
        if filtros_texto:
            base += " " + filtros_texto
    elif dimensiones:
        base = f"Distribución de {objetivo}"
        if filtros_texto:
            base += " " + filtros_texto
    else:
        original = str(intencion.get("_consulta_original") or "").strip().lower()
        pide_cantidad = bool(re.match(r"^(?:cantidad|numero|número|total)\b", original))
        if version < 2:
            cantidad = len(plan.get("filtros") or []) <= 1 or pide_cantidad
        else:
            cantidad = pide_cantidad or not filtros_texto
        # Si sexo ya determina el sustantivo, evita "personas mujeres".
        if objetivo == "personas" and filtros_texto.startswith("mujeres"):
            base = "Cantidad de mujeres" if cantidad else "Mujeres"
            filtros_texto = filtros_texto[len("mujeres"):].strip()
        elif objetivo == "personas" and filtros_texto.startswith("hombres"):
            base = "Cantidad de hombres" if cantidad else "Hombres"
            filtros_texto = filtros_texto[len("hombres"):].strip()
        else:
            base = f"Cantidad de {objetivo}" if cantidad else objetivo.capitalize()
        if filtros_texto:
            base += " " + filtros_texto

    if dimensiones:
        dims = " y ".join(
            str(d.get("etiqueta") or _descripcion_variable(d["tabla"], d["variable"])).lower()
            for d in dimensiones
        )
        base += f" según {dims}"
    if porcentaje:
        base_pct = porcentaje.get("base")
        if base_pct == "fila":
            base += ", porcentaje dentro de la primera variable"
        elif base_pct == "columna":
            base += ", porcentaje dentro de la segunda variable"

    return f"{base}, {_frase_geografica(intencion)}."



def _descripcion_movilidad_laboral_fase1(intencion):
    indicador = intencion.get("movilidad_indicador")
    titulos = {
        "salientes_cantidad": "Cantidad de personas ocupadas que trabajan fuera de su comuna de residencia",
        "misma_comuna_cantidad": "Cantidad de personas ocupadas que trabajan en su misma comuna de residencia",
        "salientes_porcentaje": "Porcentaje de personas ocupadas que trabajan fuera de su comuna de residencia",
        "misma_comuna_porcentaje": "Porcentaje de personas ocupadas que trabajan en su misma comuna de residencia",
        "entrantes_cantidad": "Cantidad de personas ocupadas que llegan desde otra comuna a trabajar",
    }
    base = titulos.get(indicador, "Movilidad laboral comunal")
    geo_trabajo = indicador == "entrantes_cantidad"
    filtro = intencion.get("filtro_geografico_nivel")
    codigo = intencion.get("filtro_geografico_codigo")
    nombre = _nombre_territorio(filtro, codigo) if filtro and codigo is not None else None
    ambito = "trabajo" if geo_trabajo else "residencia"
    if filtro == "region" and nombre:
        sufijo = f"según comunas de {ambito} de la región de {nombre}"
    elif filtro == "comuna" and nombre:
        sufijo = f"en la comuna de {ambito} de {nombre}"
    else:
        sufijo = f"según comunas de {ambito}"
    return f"{base}, {sufijo}."



def _descripcion_movilidad_laboral_fase2(intencion):
    indicador = intencion.get("movilidad_indicador")
    origen = intencion.get("movilidad_origen_nombre")
    destino = intencion.get("movilidad_destino_nombre")
    top_n = int(intencion.get("movilidad_top_n") or 10)
    solo_externos = bool(intencion.get("movilidad_solo_externos"))

    if indicador == "flujo_comunal_cantidad":
        return f"Cantidad de personas ocupadas que viven en {origen} y trabajan en {destino}."

    if indicador == "destinos_principales":
        otras = "otras " if solo_externos else ""
        return (
            f"{top_n} principales {otras}comunas de trabajo de las personas ocupadas "
            f"que viven en {origen}."
        )

    if indicador == "origenes_principales":
        otras = "otras " if solo_externos else ""
        return (
            f"{top_n} principales {otras}comunas de residencia de las personas ocupadas "
            f"que trabajan en {destino}."
        )

    if indicador == "saldo_comunal":
        filtro = intencion.get("filtro_geografico_nivel")
        codigo = intencion.get("filtro_geografico_codigo")
        nombre = _nombre_territorio(filtro, codigo) if filtro and codigo is not None else None
        if filtro == "region" and nombre:
            return (
                "Saldo de movilidad laboral, calculado como personas ocupadas entrantes desde otras comunas "
                f"menos salientes hacia otras comunas, según comunas de la región de {nombre}."
            )
        if filtro == "comuna" and nombre:
            return (
                "Saldo de movilidad laboral, calculado como personas ocupadas entrantes desde otras comunas "
                f"menos salientes hacia otras comunas, en la comuna de {nombre}."
            )
        return (
            "Saldo de movilidad laboral, calculado como personas ocupadas entrantes desde otras comunas "
            "menos salientes hacia otras comunas, según comunas."
        )

    return "Movilidad laboral comunal."



def _descripcion_movilidad_laboral_fase3(intencion):
    indicador = intencion.get("movilidad_indicador")
    metrica = intencion.get("movilidad_metrica") or "cantidad"
    partes = []
    if intencion.get("movilidad_origen_nombre"):
        partes.append(f"desde {intencion['movilidad_origen_nombre']}")
    if intencion.get("movilidad_destino_nombre"):
        partes.append(f"hacia {intencion['movilidad_destino_nombre']}")
    if intencion.get("movilidad_region_origen_nombre"):
        partes.append(f"con residencia en la región de {intencion['movilidad_region_origen_nombre']}")
    if intencion.get("movilidad_region_destino_nombre"):
        partes.append(f"con trabajo en la región de {intencion['movilidad_region_destino_nombre']}")

    filtros = [f.get("etiqueta") for f in intencion.get("movilidad_filtros_persona") or [] if f.get("etiqueta")]
    filtro_txt = ("; " + ", ".join(filtros)) if filtros else ""
    diagonal = "incluyendo la misma comuna" if intencion.get("movilidad_incluir_diagonal", True) else "excluyendo la misma comuna"
    base = {
        "cantidad": "Cantidad de personas ocupadas",
        "porcentaje_origen": "Porcentaje por comuna de residencia de personas ocupadas",
        "porcentaje_destino": "Porcentaje por comuna de trabajo de personas ocupadas",
    }.get(metrica, "Personas ocupadas")

    ambito = (" " + " ".join(partes)) if partes else ""
    if indicador == "ranking_flujos_comunales":
        top_n = int(intencion.get("movilidad_top_n") or 20)
        return f"{top_n} principales flujos laborales entre comunas{ambito}, {diagonal}{filtro_txt}."
    return f"Matriz de movilidad laboral entre comuna de residencia y comuna de trabajo: {base.lower()}{ambito}, {diagonal}{filtro_txt}."



def _descripcion_migracion_interna(intencion):
    indicador = intencion.get("migracion_indicador")
    nivel = intencion.get("migracion_nivel") or intencion.get("nivel_geografico") or "comuna"
    plural = "comunas" if nivel == "comuna" else "regiones"
    unidad = "comuna" if nivel == "comuna" else "región"
    ambito = intencion.get("migracion_ambito_region_nombre")
    filtros = [f.get("etiqueta") for f in intencion.get("migracion_filtros_persona") or [] if f.get("etiqueta")]
    filtro_txt = ("; " + ", ".join(filtros)) if filtros else ""

    if indicador == "inmigrantes_internos":
        suf = f" de la región de {ambito}" if ambito and nivel == "comuna" else ""
        return f"Cantidad de inmigrantes internos, según {plural} de residencia actual{suf}{filtro_txt}."
    if indicador == "emigrantes_internos":
        suf = f" de la región de {ambito}" if ambito and nivel == "comuna" else ""
        return f"Cantidad de emigrantes internos, según {plural} de residencia en abril de 2019{suf}{filtro_txt}."
    if indicador == "saldo_migratorio_interno":
        suf = f" de la región de {ambito}" if ambito and nivel == "comuna" else ""
        return (f"Saldo migratorio interno 2019–2024, calculado como inmigrantes internos menos emigrantes internos, "
                f"según {plural}{suf}{filtro_txt}.")

    origen = intencion.get("migracion_origen_nombre")
    destino = intencion.get("migracion_destino_nombre")
    if indicador == "flujo_migratorio_dirigido":
        return (f"Cantidad de personas que residían en {origen} en abril de 2019 y actualmente residen en {destino}{filtro_txt}.")
    top_n = int(intencion.get("migracion_top_n") or 20)
    if indicador == "destinos_migratorios_principales":
        return f"{top_n} principales {plural} de residencia actual de las personas que residían en {origen} en abril de 2019{filtro_txt}."
    if indicador == "origenes_migratorios_principales":
        return f"{top_n} principales {plural} de residencia en abril de 2019 de las personas que actualmente residen en {destino}{filtro_txt}."

    metrica = intencion.get("migracion_metrica") or "cantidad"
    base = {
        "cantidad": "cantidad de personas",
        "porcentaje_origen": f"porcentaje por {unidad} de residencia en abril de 2019",
        "porcentaje_destino": f"porcentaje por {unidad} de residencia actual",
    }.get(metrica, "cantidad de personas")
    partes = []
    if intencion.get("migracion_region_origen_nombre"):
        partes.append(f"con origen en la región de {intencion['migracion_region_origen_nombre']}")
    if intencion.get("migracion_region_destino_nombre"):
        partes.append(f"con destino actual en la región de {intencion['migracion_region_destino_nombre']}")
    alcance = (" " + " ".join(partes)) if partes else ""
    diagonal = f"incluyendo permanencia en la misma {unidad}" if intencion.get("migracion_incluir_diagonal", False) else f"excluyendo permanencia en la misma {unidad}"
    if indicador == "ranking_flujos_migratorios":
        return f"{top_n} principales flujos de migración interna entre {plural}{alcance}, {diagonal}{filtro_txt}."
    return (f"Matriz de migración interna 2019–2024 entre {unidad} de residencia en abril de 2019 y {unidad} de residencia actual: "
            f"{base}{alcance}, {diagonal}{filtro_txt}.")


def _descripcion_indicador_derivado_v24(intencion):
    titulos = {
        "envejecimiento": "Índice de envejecimiento (personas de 60 años o más por cada 100 personas de 0 a 14 años)",
        "dependencia_total": "Índice de dependencia total (IDD) (personas de 0 a 14 años y de 60 años o más por cada 100 personas de 15 a 59 años)",
        "dependencia_juvenil": "Índice de dependencia juvenil (personas de 0 a 14 años por cada 100 personas de 15 a 59 años)",
        "dependencia_mayores": "Índice de dependencia de mayores (personas de 60 años o más por cada 100 personas de 15 a 59 años)",
        "tasa_ocupacion": "Tasa de ocupación (personas ocupadas por cada 100 personas de 15 años o más)",
        "tasa_desocupacion": "Tasa de desocupación (personas desocupadas por cada 100 personas en la fuerza de trabajo)",
    }
    base = titulos.get(intencion.get("indicador_id"), str(intencion.get("indicador_descripcion") or "Indicador"))
    return f"{base}, {_frase_geografica(intencion)}."


def _descripcion_lengua_indigena_especifica(intencion):
    etiqueta = str(intencion.get("lengua_etiqueta") or "lengua indígena").strip()
    etiqueta = re.sub(r"\s*\(.*?\)\s*$", "", etiqueta).strip()
    prefijo = "Porcentaje de" if intencion.get("operacion") == "porcentaje" else "Cantidad de"
    return f"{prefijo} personas que hablan o entienden {etiqueta}, {_frase_geografica(intencion)}."

def _descripcion_indicador_censal_v27(intencion):
    base = str(intencion.get("indicador_descripcion") or "Indicador censal")
    return f"{base}, {_frase_geografica(intencion)}."


def descripcion_cotidiana(intencion):
    """Título natural compartido por leyenda del mapa y exportación Excel."""
    if intencion.get("tipo_consulta") in {"indicador_censal_v27", "distribucion_censal_v27"}:
        return _descripcion_indicador_censal_v27(intencion)
    if intencion.get("tipo_consulta") == "indicador_derivado_v24":
        return _descripcion_indicador_derivado_v24(intencion)
    if intencion.get("tipo_consulta") == "lengua_indigena_especifica":
        return _descripcion_lengua_indigena_especifica(intencion)
    if intencion.get("tipo_consulta") in {"migracion_interna_od", "migracion_interna_indicadores"}:
        return _descripcion_migracion_interna(intencion)
    if intencion.get("tipo_consulta") == "movilidad_laboral_fase3":
        return _descripcion_movilidad_laboral_fase3(intencion)
    if intencion.get("tipo_consulta") == "movilidad_laboral_fase2":
        return _descripcion_movilidad_laboral_fase2(intencion)
    if intencion.get("tipo_consulta") == "movilidad_laboral_fase1":
        return _descripcion_movilidad_laboral_fase1(intencion)
    if intencion.get("tipo_consulta") == "cruce":
        return _descripcion_plan_natural(intencion)

    if intencion.get("tipo_consulta") == "dimensiones_funcionales":
        severidad = intencion.get("severidad_etiqueta") or intencion.get("indicador_descripcion")
        base = "Personas según dimensión de dificultad funcional"
        if severidad:
            limpio = re.sub(r"^(?:sí|si)\s*,?\s*", "", str(severidad), flags=re.I)
            base = f"Personas con {limpio.lower()} según dimensión de dificultad funcional"
        return f"{base}, {_frase_geografica(intencion)}."

    operacion = intencion.get("operacion", "conteo")
    tabla = intencion["tabla"]
    variable = intencion["variable"]
    info = VARIABLES[tabla]["variables"][variable]
    categoria = intencion.get("categoria_valor")
    etiqueta = info.get("categorias", {}).get(str(categoria)) if categoria is not None else None

    if operacion == "distribucion":
        base = f"Distribución de {tabla} según {_descripcion_variable(tabla, variable).lower()}"
    elif operacion == "promedio":
        base = f"Promedio de {_descripcion_variable(tabla, variable).lower()}"
    elif operacion == "porcentaje":
        base = f"Porcentaje de {tabla}"
    elif operacion == "razon" and intencion.get("indicador_descripcion"):
        base = str(intencion["indicador_descripcion"])
    else:
        base = f"Cantidad de {tabla}"

    if etiqueta and operacion != "distribucion":
        frase = _frase_filtro({
            "tabla": tabla, "variable": variable, "tipo": "categoria",
            "valores": [str(categoria)], "etiqueta": etiqueta,
        }, tabla)
        if frase:
            base += " " + frase

    # Conserva filtros numéricos adicionales cuando la consulta no fue llevada
    # al planificador de cruces.
    for filtro in intencion.get("filtros_numericos") or []:
        frase = _frase_filtro({"tabla": tabla, "tipo": "rango", **filtro}, tabla)
        if frase:
            base += " " + frase

    return f"{base}, {_frase_geografica(intencion)}."

