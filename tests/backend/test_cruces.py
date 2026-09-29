# -*- coding: utf-8 -*-
import unittest

from nl_parser import interpretar_consulta
from categorical_resolver import AmbiguedadVariable
from union_resolver import UNION_ESTADO_CIVIL


class CrucesParserTests(unittest.TestCase):
    def test_sexo_por_tipologia_hogar(self):
        i = interpretar_consulta("personas por sexo según tipología de hogar por región")
        self.assertEqual(i["tipo_consulta"], "cruce")
        p = i["plan_cruce"]
        self.assertEqual(p["entidad_objetivo"], "personas")
        self.assertEqual([(d["tabla"], d["variable"]) for d in p["dimensiones"]],
                         [("personas", "sexo"), ("hogares", "tipologia_hogar")])

    def test_sexo_con_internet_fija(self):
        i = interpretar_consulta(
            "distribución por sexo de personas que viven en hogares con internet fija por comuna"
        )
        p = i["plan_cruce"]
        self.assertEqual(p["entidad_objetivo"], "personas")
        self.assertEqual(p["dimensiones"][0]["variable"], "sexo")
        self.assertTrue(any(f["variable"] == "p15d_serv_internet_fija" and f["valores"] == ["1"]
                            for f in p["filtros"]))

    def test_dos_filtros_entidades_distintas(self):
        i = interpretar_consulta("personas con discapacidad que viven solas por región")
        p = i["plan_cruce"]
        self.assertEqual(p["entidad_objetivo"], "personas")
        self.assertFalse(p["dimensiones"])
        self.assertEqual({(f["tabla"], f["variable"]) for f in p["filtros"]},
                         {("personas", "discapacidad"), ("hogares", "tipologia_hogar")})

    def test_ocupados_arrendadas_cuenta_personas(self):
        i = interpretar_consulta("ocupados que viven en viviendas arrendadas por comuna")
        self.assertEqual(i["plan_cruce"]["entidad_objetivo"], "personas")

    def test_hogares_tipo_vivienda_cuenta_hogares(self):
        i = interpretar_consulta("hogares según tipo de vivienda por región")
        self.assertEqual(i["plan_cruce"]["entidad_objetivo"], "hogares")
        self.assertEqual(i["plan_cruce"]["dimensiones"][0]["variable"], "p2_tipo_vivienda")

    def test_entidad_inferior_prevalece(self):
        i = interpretar_consulta("viviendas según sexo del jefe de hogar por comuna")
        self.assertEqual(i["plan_cruce"]["entidad_objetivo"], "personas")
        self.assertTrue(any(f["variable"] == "parentesco" and f["valores"] == ["1"]
                            for f in i["plan_cruce"]["filtros"]))

    def test_tres_entidades_y_filtro_geografico(self):
        i = interpretar_consulta(
            "personas de 65 años o más que viven en hogares unipersonales y viviendas rurales "
            "por comuna de la región 13"
        )
        p = i["plan_cruce"]
        self.assertEqual(p["entidad_objetivo"], "personas")
        self.assertEqual(i["nivel_geografico"], "comuna")
        self.assertEqual(i["filtro_geografico_nivel"], "region")
        self.assertEqual(int(i["filtro_geografico_codigo"]), 13)
        self.assertTrue(any(f["variable"] == "edad" and f.get("minimo") == 65
                            for f in p["filtros"]))

    def test_educacion_media_con_tipologia(self):
        i = interpretar_consulta("estudiantes de educación media según tipología de hogar por región")
        p = i["plan_cruce"]
        self.assertEqual([(d["tabla"], d["variable"]) for d in p["dimensiones"]],
                         [("hogares", "tipologia_hogar")])
        self.assertTrue(any(f["variable"] == "asistencia_media" and f["valores"] == ["1"]
                            for f in p["filtros"]))

    def test_discapacidad_p32_con_tipologia(self):
        i = interpretar_consulta(
            "personas con mucha dificultad para caminar según tipología de hogar por región"
        )
        p = i["plan_cruce"]
        self.assertTrue(any(f["variable"] == "p32c_dificultad_mover" and f["valores"] == ["3"]
                            for f in p["filtros"]))

    def test_porcentaje_cruzado_con_una_dimension_usa_total(self):
        i = interpretar_consulta("porcentaje de personas con internet fija por sexo")
        self.assertEqual(i["tipo_consulta"], "cruce")
        self.assertEqual(i["operacion"], "porcentaje")
        self.assertEqual(i["plan_cruce"]["porcentaje"]["base"], "total")
        self.assertEqual(i["plan_cruce"]["dimensiones"][0]["variable"], "sexo")

    def test_consulta_simple_no_se_convierte_en_cruce(self):
        i = interpretar_consulta("viviendas particulares por comuna")
        self.assertNotEqual(i.get("tipo_consulta"), "cruce")
        self.assertEqual(i["tabla"], "viviendas")
        self.assertEqual(i["categoria_valor"], "2")


try:
    import duckdb  # noqa: F401
    import data_engine
except ModuleNotFoundError:
    data_engine = None


@unittest.skipIf(data_engine is None, "DuckDB no está instalado en este entorno")
class CrucesSQLTests(unittest.TestCase):
    def test_sql_join_y_count_distinct(self):
        from pathlib import Path
        original = data_engine._ruta_parquet
        data_engine._ruta_parquet = lambda tabla: Path(f"C:/tmp/{tabla}.parquet")
        try:
            i = interpretar_consulta("personas por sexo según tipología de hogar por región")
            sql, _ = data_engine._construir_sql_cruce(i)
        finally:
            data_engine._ruta_parquet = original
        self.assertIn("JOIN read_parquet", sql)
        self.assertIn("p.id_vivienda = h.id_vivienda", sql)
        self.assertIn("p.id_hogar = h.id_hogar", sql)
        self.assertIn("COUNT(DISTINCT", sql)
        self.assertIn('CAST(p."sexo" AS VARCHAR) AS d0', sql)
        self.assertIn('CAST(h."tipologia_hogar" AS VARCHAR) AS d1', sql)

    def test_sql_tres_entidades(self):
        from pathlib import Path
        original = data_engine._ruta_parquet
        data_engine._ruta_parquet = lambda tabla: Path(f"C:/tmp/{tabla}.parquet")
        try:
            i = interpretar_consulta(
                "personas de 65 años o más que viven en hogares unipersonales y viviendas rurales "
                "por comuna de la región 13"
            )
            sql, _ = data_engine._construir_sql_cruce(i)
        finally:
            data_engine._ruta_parquet = original
        self.assertIn("JOIN read_parquet('C:/tmp/hogares.parquet')", sql)
        self.assertIn("JOIN read_parquet('C:/tmp/viviendas.parquet')", sql)
        self.assertIn('TRY_CAST(p."edad" AS DOUBLE) >= 65', sql)
        self.assertIn('p."region" = 13', sql)


if __name__ == "__main__":
    unittest.main()


class CrucesRegresionPantallazosTests(unittest.TestCase):
    """Regresiones construidas desde consultas reales observadas en el visor."""

    def test_tipologia_nuclear_restringe_dimension(self):
        i = interpretar_consulta(
            "personas por sexo según tipología nuclear de hogar por región"
        )
        self.assertEqual(i["tipo_consulta"], "cruce")
        dims = i["plan_cruce"]["dimensiones"]
        tipologia = next(d for d in dims if d["variable"] == "tipologia_hogar")
        self.assertEqual(tipologia["categorias_validas"], ["2", "3", "4"])

    def test_sexo_mayores_sin_espacio(self):
        i = interpretar_consulta("personas por sexomayores de 65 años")
        self.assertEqual(i["tipo_consulta"], "cruce")
        p = i["plan_cruce"]
        self.assertEqual([(d["tabla"], d["variable"]) for d in p["dimensiones"]],
                         [("personas", "sexo")])
        edad = next(f for f in p["filtros"] if f["variable"] == "edad")
        self.assertEqual(edad["minimo"], 65)
        self.assertFalse(edad["incluir_minimo"])
        self.assertIn("sexo mayores", i["_consulta_normalizada"])

    def test_situacion_fuerza_trabajo_simple_sigue_univariada(self):
        i = interpretar_consulta("situación en la fuerza de trabajo por región")
        self.assertNotEqual(i.get("tipo_consulta"), "cruce")
        self.assertEqual(i["variable"], "sit_fuerza_trabajo")
        self.assertEqual(i["operacion"], "distribucion")

    def test_hombres_es_filtro_no_dimension(self):
        i = interpretar_consulta("hombres según situación en la fuerza de trabajo por región")
        p = i["plan_cruce"]
        self.assertEqual([(d["tabla"], d["variable"]) for d in p["dimensiones"]],
                         [("personas", "sit_fuerza_trabajo")])
        sexo = next(f for f in p["filtros"] if f["variable"] == "sexo")
        self.assertEqual(sexo["valores"], ["1"])
        self.assertIn("Sexo = Hombre", i["indicador_descripcion"])

    def test_personas_que_viven_en_departamentos_cuenta_personas(self):
        i = interpretar_consulta("personas que viven en departamentos por región")
        self.assertEqual(i["tipo_consulta"], "cruce")
        p = i["plan_cruce"]
        self.assertEqual(p["entidad_objetivo"], "personas")
        self.assertFalse(p["dimensiones"])
        depa = next(f for f in p["filtros"] if f["variable"] == "p2_tipo_vivienda")
        self.assertEqual(depa["tabla"], "viviendas")
        self.assertEqual(depa["valores"], ["3"])

    def test_mayores_de_es_estricto_y_65_o_mas_inclusivo(self):
        i1 = interpretar_consulta("personas por sexo mayores de 65 años")
        f1 = next(f for f in i1["plan_cruce"]["filtros"] if f["variable"] == "edad")
        self.assertFalse(f1["incluir_minimo"])
        i2 = interpretar_consulta("personas por sexo de 65 años o más")
        f2 = next(f for f in i2["plan_cruce"]["filtros"] if f["variable"] == "edad")
        self.assertTrue(f2["incluir_minimo"])

    def test_servicio_domestico_como_parentesco(self):
        i = interpretar_consulta("personas de servicio doméstico por región")
        self.assertEqual(i["tipo_consulta"], "cruce")
        p = i["plan_cruce"]
        self.assertEqual(p["entidad_objetivo"], "personas")
        self.assertFalse(p["dimensiones"])
        f = next(f for f in p["filtros"] if f["variable"] == "parentesco")
        self.assertEqual(f["valores"], ["16"])

    def test_union_civil_ahora_exige_desambiguacion(self):
        with self.assertRaises(AmbiguedadVariable):
            interpretar_consulta("personas conviviente por acuerdo de unión civil")

    def test_nietos_que_viven_con_mayores_usan_existencia_hogar(self):
        i = interpretar_consulta("cantidad de nietos que viven con personas mayores de 65 años")
        p = i["plan_cruce"]
        nieto = next(f for f in p["filtros"] if f["variable"] == "parentesco")
        self.assertEqual(nieto["valores"], ["12"])
        self.assertTrue(any(f["tipo"] == "existe_en_hogar" for f in p["filtros"]))
        self.assertFalse(any(f["tipo"] == "rango" and f["variable"] == "edad" for f in p["filtros"]))

    def test_personas_que_viven_con_mayores_no_filtra_edad_propias(self):
        i = interpretar_consulta("cantidad de personas que viven con personas mayores de 65 años")
        p = i["plan_cruce"]
        self.assertTrue(any(f["tipo"] == "existe_en_hogar" for f in p["filtros"]))
        self.assertFalse(any(f["tipo"] == "rango" and f["variable"] == "edad" for f in p["filtros"]))


@unittest.skipIf(data_engine is None, "DuckDB no está instalado en este entorno")
class CrucesSQLRegresionPantallazosTests(unittest.TestCase):
    def _sql(self, pregunta):
        from pathlib import Path
        original = data_engine._ruta_parquet
        data_engine._ruta_parquet = lambda tabla: Path(f"C:/tmp/{tabla}.parquet")
        try:
            i = interpretar_consulta(pregunta)
            return data_engine._construir_sql_cruce(i)[0]
        finally:
            data_engine._ruta_parquet = original

    def test_sql_hombres_aplica_filtro_sexo(self):
        sql = self._sql("hombres según situación en la fuerza de trabajo por región")
        self.assertIn('CAST(p."sexo" AS VARCHAR) IN (\'1\')', sql)

    def test_sql_departamentos_une_viviendas_y_cuenta_personas(self):
        sql = self._sql("personas que viven en departamentos por región")
        self.assertIn("JOIN read_parquet('C:/tmp/viviendas.parquet') v", sql)
        self.assertIn('CAST(v."p2_tipo_vivienda" AS VARCHAR) IN (\'3\')', sql)
        self.assertIn('CAST(p.id_persona AS VARCHAR)', sql)

    def test_sql_tipologia_nuclear_excluye_no_nucleares(self):
        sql = self._sql("personas por sexo según tipología nuclear de hogar por región")
        self.assertIn('CAST(h."tipologia_hogar" AS VARCHAR) IN (\'2\', \'3\', \'4\')', sql)
        self.assertNotIn("'1', '2', '3', '4', '5', '6', '7'", sql)

    def test_sql_mayores_65_es_estricto(self):
        sql = self._sql("personas por sexomayores de 65 años")
        self.assertIn('TRY_CAST(p."edad" AS DOUBLE) > 65', sql)

    def test_sql_servicio_domestico_parentesco_16(self):
        sql = self._sql("personas de servicio doméstico por región")
        self.assertIn('CAST(p."parentesco" AS VARCHAR) IN (\'16\')', sql)

    def test_sql_conviviente_civil_estado_civil_3(self):
        from pathlib import Path
        original = data_engine._ruta_parquet
        data_engine._ruta_parquet = lambda tabla: Path(f"C:/tmp/{tabla}.parquet")
        try:
            i = interpretar_consulta(
                "personas conviviente por acuerdo de unión civil",
                tabla_seleccionada="personas",
                variable_seleccionada=UNION_ESTADO_CIVIL,
            )
            sql = data_engine._construir_sql_cruce(i)[0]
        finally:
            data_engine._ruta_parquet = original
        self.assertIn('CAST(p."p23_est_civil" AS VARCHAR) IN (\'3\')', sql)
        self.assertNotIn('CAST(p."parentesco" AS VARCHAR) IN (\'3\')', sql)

    def test_sql_viven_con_mayores_usa_exists_en_hogar(self):
        sql = self._sql("cantidad de personas que viven con personas mayores de 65 años")
        self.assertIn("EXISTS (SELECT 1 FROM read_parquet('C:/tmp/personas.parquet') px", sql)
        self.assertIn('px.id_vivienda = p.id_vivienda', sql)
        self.assertIn('px.id_hogar = p.id_hogar', sql)
        self.assertIn('TRY_CAST(px."edad" AS DOUBLE) > 65', sql)
        self.assertNotIn('TRY_CAST(p."edad" AS DOUBLE) > 65', sql)
