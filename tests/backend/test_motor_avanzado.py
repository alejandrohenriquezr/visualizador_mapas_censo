# -*- coding: utf-8 -*-
import sys
import types
import unittest
from pathlib import Path

from categorical_resolver import AmbiguedadOperacion
from nl_parser import interpretar_consulta
from query_metadata import variable_metadata
from presentation import descripcion_cotidiana


class MetadataTests(unittest.TestCase):
    def test_edad_es_numerica(self):
        m = variable_metadata("personas", "edad")
        self.assertEqual(m["tipo"], "numerica")
        self.assertIn("promedio", m["operaciones_permitidas"])
        self.assertIn("-66", m["codigos_excluidos"])

    def test_p32_es_ordinal(self):
        m = variable_metadata("personas", "p32a_dificultad_ver")
        self.assertEqual(m["tipo"], "ordinal")
        self.assertEqual(m["categorias_validas"], ["1", "2", "3", "4"])


class MotorAvanzadoParserTests(unittest.TestCase):
    def test_or_rangos_edad(self):
        i = interpretar_consulta("personas menores de 15 o de 65 años o más por región")
        self.assertEqual(i["_origen_interpretacion"], "planificador_avanzado_v2")
        ast = i["plan_cruce"]["filtro_ast"]
        self.assertEqual(ast["op"], "or")
        self.assertEqual(len(ast["args"]), 2)

    def test_or_categorias_laborales(self):
        i = interpretar_consulta("personas ocupadas o desocupadas por sexo y región")
        ast = i["plan_cruce"]["filtro_ast"]
        self.assertEqual(ast["variable"], "sit_fuerza_trabajo")
        self.assertEqual(ast["valores"], ["1", "2"])
        self.assertEqual(i["plan_cruce"]["dimensiones"][0]["variable"], "sexo")

    def test_or_categoria_agua(self):
        i = interpretar_consulta("viviendas con agua de red pública o pozo por comuna")
        ast = i["plan_cruce"]["filtro_ast"]
        self.assertEqual((ast["tabla"], ast["variable"]), ("viviendas", "p6_fuente_agua"))
        self.assertEqual(ast["valores"], ["1", "2"])

    def test_not_jefatura(self):
        i = interpretar_consulta("personas ocupadas o desocupadas pero no jefas de hogar por región")
        ast = i["plan_cruce"]["filtro_ast"]
        self.assertEqual(ast["op"], "and")
        self.assertTrue(any(x.get("op") == "not" for x in ast["args"]))

    def test_tres_dimensiones(self):
        i = interpretar_consulta("personas por sexo, estado civil y religión por región")
        dims = [d["variable"] for d in i["plan_cruce"]["dimensiones"]]
        self.assertEqual(dims, ["sexo", "p23_est_civil", "p31_religion"])

    def test_promedio_multientidad(self):
        i = interpretar_consulta("promedio de edad según tipología de hogar por comuna")
        p = i["plan_cruce"]
        self.assertEqual(p["medida"]["operacion"], "promedio")
        self.assertEqual(p["medida"]["variable"], "edad")
        self.assertEqual(p["dimensiones"][0]["variable"], "tipologia_hogar")

    def test_mediana(self):
        i = interpretar_consulta("mediana de edad por comuna")
        self.assertEqual(i["plan_cruce"]["medida"]["operacion"], "mediana")

    def test_porcentaje_dos_dimensiones_pide_base(self):
        q = "porcentaje de personas por sexo y situación en la fuerza de trabajo por región"
        with self.assertRaises(AmbiguedadOperacion):
            interpretar_consulta(q)
        i = interpretar_consulta(q, operacion_seleccionada="__pct_fila")
        self.assertEqual(i["plan_cruce"]["porcentaje"]["base"], "fila")

    def test_porcentaje_una_dimension_total(self):
        i = interpretar_consulta("porcentaje de personas con internet fija por sexo")
        self.assertEqual(i["plan_cruce"]["porcentaje"]["base"], "total")

    def test_hogares_dos_menores(self):
        i = interpretar_consulta("hogares con 2 o más menores de 15 años por comuna")
        p = i["plan_cruce"]
        self.assertEqual(p["entidad_objetivo"], "hogares")
        self.assertEqual(p["filtro_ast"]["tipo"], "conteo_relacionado")
        self.assertEqual(p["filtro_ast"]["min_conteo"], 2)

    def test_hogares_todos_mayores(self):
        i = interpretar_consulta("hogares donde todas las personas son de 65 años o más por región")
        p = i["plan_cruce"]
        self.assertEqual(p["entidad_objetivo"], "hogares")
        self.assertEqual(p["filtro_ast"]["tipo"], "no_existe_en_hogar")

    def test_seleccion_multiple_regiones(self):
        i = interpretar_consulta("personas por sexo por comuna en regiones 5, 8 y 13")
        self.assertEqual(i["nivel_geografico"], "comuna")
        self.assertIsNone(i["filtro_geografico_nivel"])
        self.assertEqual(i["plan_cruce"]["selecciones_geograficas"][0]["codigos"], [5, 8, 13])

    def test_recode_edad_usuario(self):
        i = interpretar_consulta("personas por grupos de edad 0-14, 15-29, 30-64 y 65+ por región")
        dims = i["plan_cruce"]["dimensiones"]
        self.assertEqual(len(dims), 1)
        self.assertEqual(dims[0]["tipo"], "recode_rangos")
        self.assertEqual([g["etiqueta"] for g in dims[0]["grupos"]], ["0-14", "15-29", "30-64", "65+"])

    def test_hogares_con_persona_discapacidad_no_crea_dimension(self):
        i = interpretar_consulta("hogares con al menos una persona con discapacidad por región")
        p = i["plan_cruce"]
        self.assertEqual(p["entidad_objetivo"], "hogares")
        self.assertEqual(p["dimensiones"], [])
        self.assertEqual(p["filtro_ast"]["tipo"], "existe_en_hogar")
        self.assertEqual(p["filtro_ast"]["subfiltros"][0]["variable"], "discapacidad")

    def test_seleccion_multiple_regiones_por_nombre(self):
        i = interpretar_consulta(
            "personas por sexo por comuna en regiones de Valparaíso, Biobío y Metropolitana de Santiago"
        )
        self.assertEqual(i["nivel_geografico"], "comuna")
        self.assertIsNone(i["filtro_geografico_nivel"])
        self.assertEqual(i["plan_cruce"]["selecciones_geograficas"][0]["codigos"], [5, 8, 13])

    def test_viviendas_con_persona_mayor_y_dificultad_visual(self):
        i = interpretar_consulta(
            "Cantidad de viviendas donde habitan personas mayores de 65 años con mucha dificultad visual "
            "por comuna de la región de la araucanía"
        )
        p = i["plan_cruce"]
        self.assertEqual(i["_origen_interpretacion"], "planificador_avanzado_v2")
        self.assertEqual(p["entidad_objetivo"], "viviendas")
        self.assertEqual(p["filtro_ast"]["tipo"], "existe_en_hogar")
        subs = p["filtro_ast"]["subfiltros"]
        self.assertTrue(any(f.get("variable") == "edad" and f.get("minimo") == 65 and not f.get("incluir_minimo") for f in subs))
        self.assertTrue(any(f.get("variable") == "p32a_dificultad_ver" and f.get("valores") == ["3"] for f in subs))
        self.assertEqual(i["nivel_geografico"], "comuna")
        self.assertEqual(i["filtro_geografico_nivel"], "region")
        self.assertEqual(int(i["filtro_geografico_codigo"]), 9)

    def test_viviendas_con_mujeres_mantiene_vivienda_como_objetivo(self):
        i = interpretar_consulta(
            "Cantidad de viviendas donde habitan personas mujeres por comuna de la región de la araucanía"
        )
        p = i["plan_cruce"]
        self.assertEqual(p["entidad_objetivo"], "viviendas")
        self.assertEqual(p["filtro_ast"]["subfiltros"][0]["variable"], "sexo")
        self.assertEqual(p["filtro_ast"]["subfiltros"][0]["valores"], ["2"])

    def test_viviendas_con_typo_mijeres_usa_normalizacion_previa(self):
        i = interpretar_consulta(
            "Cantidad de viviendas donde habitan personas mijeres por comuna de la región de la araucanía"
        )
        self.assertEqual(i["plan_cruce"]["entidad_objetivo"], "viviendas")
        self.assertIn("personas mujeres", i["_consulta_normalizada"])

    def test_viviendas_con_personas_15_o_menos(self):
        i = interpretar_consulta(
            "Cantidad de viviendas donde habitan personas de 15 años o menos por comuna de la región de la araucanía"
        )
        p = i["plan_cruce"]
        self.assertEqual(p["entidad_objetivo"], "viviendas")
        edad = next(f for f in p["filtro_ast"]["subfiltros"] if f.get("variable") == "edad")
        self.assertEqual(edad["maximo"], 15)
        self.assertTrue(edad["incluir_maximo"])

    def test_viviendas_con_personas_menores_a_15(self):
        i = interpretar_consulta(
            "Cantidad de viviendas donde habitan personas menores a 15 años por comuna de la región de la araucanía"
        )
        edad = next(f for f in i["plan_cruce"]["filtro_ast"]["subfiltros"] if f.get("variable") == "edad")
        self.assertEqual(edad["maximo"], 15)
        self.assertFalse(edad["incluir_maximo"])

    def test_hogares_donde_viven_mujeres_cuenta_hogares(self):
        i = interpretar_consulta("Cantidad de hogares donde viven personas mujeres por región")
        self.assertEqual(i["plan_cruce"]["entidad_objetivo"], "hogares")
        self.assertEqual(i["plan_cruce"]["filtro_ast"]["tipo"], "existe_en_hogar")

    def test_viviendas_donde_habitan_mujeres_sin_palabra_personas(self):
        q = "Cantidad de viviendas donde habitan mujeres por comuna de la región de la araucanía"
        i = interpretar_consulta(q)
        p = i["plan_cruce"]
        self.assertEqual(p["entidad_objetivo"], "viviendas")
        self.assertEqual(p["filtro_ast"]["tipo"], "existe_en_hogar")
        sexo = next(f for f in p["filtro_ast"]["subfiltros"] if f.get("variable") == "sexo")
        self.assertEqual(sexo["valores"], ["2"])
        titulo = descripcion_cotidiana(i)
        self.assertTrue(titulo.startswith("Cantidad de viviendas"), titulo)
        self.assertIn("mujer", titulo.lower())
        self.assertNotIn("Cantidad de personas", titulo)

    def test_viviendas_donde_habitan_mujeres_mayores_65_leyenda(self):
        q = "Cantidad de viviendas donde habitan mujeres mayores de 65 años por comuna de la región de la araucanía"
        i = interpretar_consulta(q)
        p = i["plan_cruce"]
        self.assertEqual(p["entidad_objetivo"], "viviendas")
        subs = p["filtro_ast"]["subfiltros"]
        self.assertTrue(any(f.get("variable") == "sexo" and f.get("valores") == ["2"] for f in subs))
        self.assertTrue(any(f.get("variable") == "edad" and f.get("minimo") == 65 and not f.get("incluir_minimo") for f in subs))
        titulo = descripcion_cotidiana(i)
        self.assertTrue(titulo.startswith("Cantidad de viviendas"), titulo)
        self.assertIn("mujer mayor de 65 años", titulo.lower())

    def test_viviendas_personas_discapacitadas_equivale_con_discapacidad(self):
        for q in (
            "Cantidad de viviendas donde habitan personas discapacitadas por comuna de la región de la araucanía",
            "Cantidad de viviendas con personas discapacitadas por comuna de la región de la araucanía",
        ):
            with self.subTest(q=q):
                i = interpretar_consulta(q)
                p = i["plan_cruce"]
                self.assertEqual(p["entidad_objetivo"], "viviendas")
                self.assertEqual(p["filtro_ast"]["tipo"], "existe_en_hogar")
                discapacidad = next(f for f in p["filtro_ast"]["subfiltros"] if f.get("variable") == "discapacidad")
                self.assertEqual(discapacidad["valores"], ["1"])
                titulo = descripcion_cotidiana(i)
                self.assertTrue(titulo.startswith("Cantidad de viviendas"), titulo)
                self.assertIn("con discapacidad", titulo.lower())
                self.assertNotEqual(titulo, "Cantidad de viviendas, según comunas de la región de La Araucanía.")

    def test_personas_discapacitadas_equivale_con_discapacidad(self):
        a = interpretar_consulta("personas discapacitadas por región")
        b = interpretar_consulta("personas con discapacidad por región")
        self.assertEqual((a["tabla"], a["variable"], a["categoria_valor"]),
                         ("personas", "discapacidad", "1"))
        self.assertEqual((b["tabla"], b["variable"], b["categoria_valor"]),
                         ("personas", "discapacidad", "1"))
        self.assertIn("con discapacidad", descripcion_cotidiana(a).lower())

    def test_demonimo_venezolano_seleccion_nacimiento_no_reabre(self):
        i = interpretar_consulta(
            "personas venezolanas por región",
            tabla_seleccionada="personas", variable_seleccionada="p25_lug_nacimiento_esp",
        )
        p = i["plan_cruce"]
        f = next(x for x in p["filtros"] if x.get("variable") == "p25_lug_nacimiento_esp")
        self.assertEqual(f["valores"], ["862"])
        self.assertIn("nacidas en venezuela", descripcion_cotidiana(i).lower())

    def test_demonimo_venezolano_seleccion_nacionalidad_no_reabre(self):
        i = interpretar_consulta(
            "personas venezolanas por región",
            tabla_seleccionada="personas", variable_seleccionada="p27_nacionalidad_esp",
        )
        p = i["plan_cruce"]
        f = next(x for x in p["filtros"] if x.get("variable") == "p27_nacionalidad_esp")
        self.assertEqual(f["valores"], ["862"])
        self.assertIn("nacionalidad venezuela", descripcion_cotidiana(i).lower())

    def test_nacionalidad_venezolana_con_rango_es_filtro_no_dimension(self):
        i = interpretar_consulta("personas de nacionalidad venezolana entre 20 y 50 años por región")
        p = i["plan_cruce"]
        self.assertEqual(p["dimensiones"], [])
        nacionalidad = next(f for f in p["filtros"] if f.get("variable") == "p27_nacionalidad_esp")
        edad = next(f for f in p["filtros"] if f.get("variable") == "edad")
        self.assertEqual(nacionalidad["valores"], ["862"])
        self.assertEqual((edad["minimo"], edad["maximo"]), (20, 50))
        titulo = descripcion_cotidiana(i).lower()
        self.assertIn("nacionalidad venezuela", titulo)
        self.assertIn("entre 20 y 50 años", titulo)
        self.assertNotIn("distribución", titulo)

    def test_mujeres_con_hijos_20_50_aplica_tres_condiciones(self):
        i = interpretar_consulta("mujeres con hijos entre 20 y 50 años por región")
        p = i["plan_cruce"]
        self.assertEqual(p["entidad_objetivo"], "personas")
        self.assertEqual(p["dimensiones"], [])
        filtros = p["filtros"]
        self.assertTrue(any(f.get("variable") == "sexo" and f.get("valores") == ["2"] for f in filtros))
        self.assertTrue(any(f.get("variable") == "edad" and f.get("minimo") == 20 and f.get("maximo") == 50 for f in filtros))
        self.assertTrue(any(f.get("variable") == "p46a_tot_hijs_nac" and f.get("minimo") == 0 and not f.get("incluir_minimo") for f in filtros))
        self.assertFalse(any(f.get("variable") == "parentesco" and f.get("valores") == ["5"] for f in filtros))
        titulo = descripcion_cotidiana(i).lower()
        self.assertTrue(titulo.startswith("mujeres"), titulo)
        self.assertIn("al menos una hija o hijo nacido vivo", titulo)
        self.assertIn("entre 20 y 50 años", titulo)


# El compilador SQL no necesita conectarse a DuckDB. Si el paquete no está
# instalado en este entorno de construcción, se inyecta un módulo mínimo para
# poder importar data_engine y revisar el SQL generado.
try:
    import duckdb  # noqa: F401
except ModuleNotFoundError:
    sys.modules["duckdb"] = types.SimpleNamespace(connect=lambda *a, **k: None)

import data_engine  # noqa: E402


class MotorAvanzadoSQLTests(unittest.TestCase):
    def setUp(self):
        self.original = data_engine._ruta_parquet
        data_engine._ruta_parquet = lambda tabla: Path(f"C:/tmp/{tabla}.parquet")

    def tearDown(self):
        data_engine._ruta_parquet = self.original

    def sql(self, q, sel=None):
        i = interpretar_consulta(q, operacion_seleccionada=sel)
        return data_engine._construir_sql_cruce(i)[0]

    def test_sql_or_edad(self):
        sql = self.sql("personas menores de 15 o de 65 años o más por región")
        self.assertIn(" OR ", sql)
        self.assertIn('TRY_CAST(p."edad" AS DOUBLE) < 15', sql)
        self.assertIn('TRY_CAST(p."edad" AS DOUBLE) >= 65', sql)

    def test_sql_not_jefe(self):
        sql = self.sql("personas ocupadas o desocupadas pero no jefas de hogar por región")
        self.assertIn("NOT (", sql)
        self.assertIn('CAST(p."parentesco" AS VARCHAR) IN (\'1\')', sql)

    def test_sql_tres_dimensiones(self):
        sql = self.sql("personas por sexo, estado civil y religión por región")
        self.assertIn('AS d0', sql)
        self.assertIn('AS d1', sql)
        self.assertIn('AS d2', sql)

    def test_sql_promedio_y_join_hogar(self):
        sql = self.sql("promedio de edad según tipología de hogar por comuna")
        self.assertIn('AVG(TRY_CAST(p."edad" AS DOUBLE)) AS valor', sql)
        self.assertIn("JOIN read_parquet('C:/tmp/hogares.parquet') h", sql)

    def test_sql_mediana(self):
        sql = self.sql("mediana de edad por comuna")
        self.assertIn('MEDIAN(TRY_CAST(p."edad" AS DOUBLE)) AS valor', sql)

    def test_sql_count_related_hogar(self):
        sql = self.sql("hogares con 2 o más menores de 15 años por comuna")
        self.assertIn("FROM read_parquet('C:/tmp/hogares.parquet') h", sql)
        self.assertIn("SELECT COUNT(DISTINCT", sql)
        self.assertIn("px.id_hogar = h.id_hogar", sql)
        self.assertIn(">= 2", sql)

    def test_sql_todos_mayores_not_exists(self):
        sql = self.sql("hogares donde todas las personas son de 65 años o más por región")
        self.assertIn("NOT (EXISTS", sql)
        self.assertIn('TRY_CAST(px."edad" AS DOUBLE) < 65', sql)

    def test_sql_seleccion_regiones(self):
        sql = self.sql("personas por sexo por comuna en regiones 5, 8 y 13")
        self.assertIn('p."region" IN (5, 8, 13)', sql)

    def test_sql_recode_edad_case(self):
        sql = self.sql("personas por grupos de edad 0-14, 15-29, 30-64 y 65+ por región")
        self.assertIn("CASE", sql)
        self.assertIn("THEN '0-14'", sql)
        self.assertIn("THEN '65+'", sql)

    def test_sql_hogar_con_persona_discapacidad_exists(self):
        sql = self.sql("hogares con al menos una persona con discapacidad por región")
        self.assertIn("FROM read_parquet('C:/tmp/hogares.parquet') h", sql)
        self.assertIn("EXISTS", sql)
        self.assertIn('CAST(px."discapacidad" AS VARCHAR) IN (\'1\')', sql)
        self.assertIn("px.id_hogar = h.id_hogar", sql)

    def test_sql_regiones_por_nombre(self):
        sql = self.sql(
            "personas por sexo por comuna en regiones de Valparaíso, Biobío y Metropolitana de Santiago"
        )
        self.assertIn('p."region" IN (5, 8, 13)', sql)

    def test_sql_viviendas_con_persona_mayor_y_dificultad(self):
        sql = self.sql(
            "Cantidad de viviendas donde habitan personas mayores de 65 años con mucha dificultad visual "
            "por comuna de la región de la araucanía"
        )
        self.assertIn("FROM read_parquet('C:/tmp/viviendas.parquet') v", sql)
        self.assertIn("COUNT(DISTINCT CAST(v.id_vivienda AS VARCHAR))", sql)
        self.assertIn("EXISTS (SELECT 1 FROM read_parquet('C:/tmp/personas.parquet') px", sql)
        self.assertIn("px.id_vivienda = v.id_vivienda", sql)
        self.assertIn('TRY_CAST(px."edad" AS DOUBLE) > 65', sql)
        self.assertIn('CAST(px."p32a_dificultad_ver" AS VARCHAR) IN (\'3\')', sql)
        self.assertIn('v."region" = 9', sql)
        self.assertNotIn("COUNT(DISTINCT concat_ws('|', CAST(p.id_vivienda", sql)

    def test_sql_viviendas_con_15_o_menos(self):
        sql = self.sql(
            "Cantidad de viviendas donde habitan personas de 15 años o menos por comuna de la región de la araucanía"
        )
        self.assertIn('TRY_CAST(px."edad" AS DOUBLE) <= 15', sql)
        self.assertIn("COUNT(DISTINCT CAST(v.id_vivienda AS VARCHAR))", sql)

    def test_sql_viviendas_con_menores_a_15(self):
        sql = self.sql(
            "Cantidad de viviendas donde habitan personas menores a 15 años por comuna de la región de la araucanía"
        )
        self.assertIn('TRY_CAST(px."edad" AS DOUBLE) < 15', sql)
        self.assertIn("COUNT(DISTINCT CAST(v.id_vivienda AS VARCHAR))", sql)

    def test_sql_hogares_donde_viven_mujeres(self):
        sql = self.sql("Cantidad de hogares donde viven personas mujeres por región")
        self.assertIn("FROM read_parquet('C:/tmp/hogares.parquet') h", sql)
        self.assertIn("COUNT(DISTINCT concat_ws('|', CAST(h.id_vivienda AS VARCHAR), CAST(h.id_hogar AS VARCHAR)))", sql)
        self.assertIn("px.id_vivienda = h.id_vivienda", sql)
        self.assertIn("px.id_hogar = h.id_hogar", sql)
        self.assertIn('CAST(px."sexo" AS VARCHAR) IN (\'2\')', sql)

    def test_sql_viviendas_donde_habitan_mujeres_sin_personas(self):
        sql = self.sql("Cantidad de viviendas donde habitan mujeres por comuna de la región de la araucanía")
        self.assertIn("FROM read_parquet('C:/tmp/viviendas.parquet') v", sql)
        self.assertIn("COUNT(DISTINCT CAST(v.id_vivienda AS VARCHAR))", sql)
        self.assertIn("EXISTS (SELECT 1 FROM read_parquet('C:/tmp/personas.parquet') px", sql)
        self.assertIn('CAST(px."sexo" AS VARCHAR) IN (\'2\')', sql)
        self.assertNotIn("COUNT(DISTINCT concat_ws('|', CAST(p.id_vivienda", sql)

    def test_sql_viviendas_mujeres_mayores_65_conjuncion_en_mismo_residente(self):
        sql = self.sql("Cantidad de viviendas donde habitan mujeres mayores de 65 años por comuna de la región de la araucanía")
        self.assertIn("COUNT(DISTINCT CAST(v.id_vivienda AS VARCHAR))", sql)
        self.assertIn('CAST(px."sexo" AS VARCHAR) IN (\'2\')', sql)
        self.assertIn('TRY_CAST(px."edad" AS DOUBLE) > 65', sql)

    def test_sql_viviendas_personas_discapacitadas(self):
        sql = self.sql("Cantidad de viviendas con personas discapacitadas por comuna de la región de la araucanía")
        self.assertIn("COUNT(DISTINCT CAST(v.id_vivienda AS VARCHAR))", sql)
        self.assertIn('CAST(px."discapacidad" AS VARCHAR) IN (\'1\')', sql)

    def test_sql_nacionalidad_venezolana_y_edad(self):
        sql = self.sql("personas de nacionalidad venezolana entre 20 y 50 años por región")
        self.assertIn('CAST(p."p27_nacionalidad_esp" AS VARCHAR) IN (\'862\')', sql)
        self.assertIn('TRY_CAST(p."edad" AS DOUBLE) >= 20', sql)
        self.assertIn('TRY_CAST(p."edad" AS DOUBLE) <= 50', sql)
        self.assertNotIn('CAST(p."p27_nacionalidad" AS VARCHAR) AS d0', sql)

    def test_sql_mujeres_con_hijos_y_edad(self):
        sql = self.sql("mujeres con hijos entre 20 y 50 años por región")
        self.assertIn('CAST(p."sexo" AS VARCHAR) IN (\'2\')', sql)
        self.assertIn('TRY_CAST(p."edad" AS DOUBLE) >= 20', sql)
        self.assertIn('TRY_CAST(p."edad" AS DOUBLE) <= 50', sql)
        self.assertIn('TRY_CAST(p."p46a_tot_hijs_nac" AS DOUBLE) > 0', sql)
        self.assertNotIn('CAST(p."parentesco" AS VARCHAR) IN (\'5\')', sql)


if __name__ == "__main__":
    unittest.main()
