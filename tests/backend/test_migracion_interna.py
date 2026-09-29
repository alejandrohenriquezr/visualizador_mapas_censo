# -*- coding: utf-8 -*-
import sys
import types
import unittest
from pathlib import Path

from nl_parser import interpretar_consulta
from presentation import descripcion_cotidiana


class MigracionInternaParserTests(unittest.TestCase):
    def test_matriz_comunal(self):
        i=interpretar_consulta('matriz de migración interna entre comunas')
        self.assertEqual(i['tipo_consulta'],'migracion_interna_od')
        self.assertEqual(i['migracion_indicador'],'matriz_migracion_interna')
        self.assertEqual(i['migracion_nivel'],'comuna')
        self.assertFalse(i['migracion_incluir_diagonal'])
        t=descripcion_cotidiana(i)
        self.assertIn('residencia en abril de 2019',t)
        self.assertIn('residencia actual',t)

    def test_matriz_regional(self):
        i=interpretar_consulta('matriz de migración interna entre regiones')
        self.assertEqual(i['migracion_nivel'],'region')
        self.assertIn('misma región',descripcion_cotidiana(i))

    def test_matriz_por_comunas_region_metropolitana_restringe_ambos_lados(self):
        i=interpretar_consulta('matriz migración interna por comunas de la región metropolitana')
        self.assertEqual(i['migracion_nivel'],'comuna')
        self.assertEqual(int(i['migracion_region_origen_codigo']),13)
        self.assertEqual(int(i['migracion_region_destino_codigo']),13)
        self.assertEqual(i['migracion_region_origen_nombre'],'Metropolitana de Santiago')
        self.assertEqual(i['migracion_region_destino_nombre'],'Metropolitana de Santiago')

    def test_ranking_top_20(self):
        i=interpretar_consulta('20 principales flujos migratorios entre comunas')
        self.assertEqual(i['migracion_indicador'],'ranking_flujos_migratorios')
        self.assertEqual(i['migracion_top_n'],20)
        self.assertTrue(descripcion_cotidiana(i).startswith('20 principales flujos'))

    def test_flujo_temporal_temucho_santiago(self):
        i=interpretar_consulta('personas que vivían en Temuco en 2019 y ahora viven en Santiago')
        self.assertEqual(i['migracion_indicador'],'flujo_migratorio_dirigido')
        self.assertEqual(int(i['migracion_origen_codigo']),9101)
        self.assertEqual(int(i['migracion_destino_codigo']),13101)
        t=descripcion_cotidiana(i)
        self.assertIn('Temuco',t); self.assertIn('Santiago',t); self.assertIn('abril de 2019',t)

    def test_destinos_desde_temucho(self):
        i=interpretar_consulta('principales destinos de quienes vivían en Temuco en 2019')
        self.assertEqual(i['migracion_indicador'],'destinos_migratorios_principales')
        self.assertEqual(int(i['migracion_origen_codigo']),9101)
        self.assertIn('residencia actual',descripcion_cotidiana(i))

    def test_origenes_hacia_temucho(self):
        i=interpretar_consulta('de qué comunas provienen quienes ahora viven en Temuco')
        self.assertEqual(i['migracion_indicador'],'origenes_migratorios_principales')
        self.assertEqual(int(i['migracion_destino_codigo']),9101)
        self.assertIn('abril de 2019',descripcion_cotidiana(i))

    def test_inmigrantes_region(self):
        i=interpretar_consulta('inmigrantes internos por región')
        self.assertEqual(i['tipo_consulta'],'migracion_interna_indicadores')
        self.assertEqual(i['migracion_indicador'],'inmigrantes_internos')
        self.assertEqual(i['migracion_nivel'],'region')
        self.assertTrue(descripcion_cotidiana(i).startswith('Cantidad de inmigrantes internos'))

    def test_emigrantes_comuna_araucania(self):
        i=interpretar_consulta('emigrantes internos por comuna de la región de la araucanía')
        self.assertEqual(i['migracion_nivel'],'comuna')
        self.assertEqual(int(i['migracion_ambito_region_codigo']),9)
        self.assertIn('La Araucanía',descripcion_cotidiana(i))

    def test_saldo_comuna_araucania(self):
        i=interpretar_consulta('saldo migratorio interno por comuna de la región de la araucanía')
        self.assertEqual(i['migracion_indicador'],'saldo_migratorio_interno')
        self.assertIn('inmigrantes internos menos emigrantes internos',descripcion_cotidiana(i))

    def test_porcentaje_origen(self):
        i=interpretar_consulta('matriz de migración interna entre comunas porcentaje por origen')
        self.assertEqual(i['migracion_metrica'],'porcentaje_origen')
        self.assertEqual(i['operacion'],'porcentaje')

    def test_porcentaje_ambiguo_pide_base(self):
        with self.assertRaisesRegex(ValueError,'porcentaje por territorio de origen'):
            interpretar_consulta('matriz de migración interna entre comunas porcentaje')

    def test_incluir_permanencia(self):
        i=interpretar_consulta('matriz de migración interna entre comunas incluyendo permanencia')
        self.assertTrue(i['migracion_incluir_diagonal'])
        self.assertIn('incluyendo permanencia',descripcion_cotidiana(i))

    def test_filtros_persona(self):
        i=interpretar_consulta('matriz de migración interna de mujeres entre 20 y 39 años entre comunas')
        fs=i['migracion_filtros_persona']
        self.assertTrue(any(f['variable']=='sexo' and f['valor']=='2' for f in fs))
        self.assertTrue(any(f['variable']=='edad' and f['op']=='between' for f in fs))

    def test_consulta_generica_pide_indicador(self):
        with self.assertRaisesRegex(ValueError,'inmigrantes internos'):
            interpretar_consulta('migración interna por región')


try:
    import duckdb  # noqa
except ModuleNotFoundError:
    sys.modules['duckdb']=types.SimpleNamespace(connect=lambda *a,**k:None)
import data_engine  # noqa: E402


class MigracionInternaSQLTests(unittest.TestCase):
    def setUp(self):
        self.original=data_engine._ruta_parquet
        data_engine._ruta_parquet=lambda tabla: Path(f'C:/tmp/{tabla}.parquet')
    def tearDown(self):
        data_engine._ruta_parquet=self.original
    def sql_od(self,q):
        i=interpretar_consulta(q); return data_engine._construir_sql_migracion_interna_od(i)[0]
    def sql_ind(self,q):
        i=interpretar_consulta(q); return data_engine._construir_sql_migracion_interna_indicadores(i)[0]

    def test_universo_p24(self):
        sql=self.sql_od('matriz de migración interna entre comunas')
        self.assertIn('p."p24_lug_resid5"',sql)
        self.assertIn("= '2'",sql); self.assertIn("= '3'",sql)
        self.assertNotIn("= '4'",sql)
        self.assertIn('p24_lug_resid5_esp',sql)

    def test_p24_misma_comuna_asigna_origen_actual(self):
        sql=self.sql_od('matriz de migración interna entre comunas incluyendo permanencia')
        self.assertIn("WHEN CAST(p.\"p24_lug_resid5\" AS VARCHAR) = '2' THEN TRY_CAST(p.\"comuna\" AS BIGINT)",sql)
        self.assertNotIn('origen <> destino',sql)

    def test_default_excluye_diagonal(self):
        sql=self.sql_od('matriz de migración interna entre comunas')
        self.assertIn('origen <> destino',sql)

    def test_regional_deriva_region_desde_comuna(self):
        sql=self.sql_od('matriz de migración interna entre regiones')
        self.assertIn('FLOOR',sql); self.assertIn('/ 1000',sql)

    def test_matriz_rm_filtra_origen_y_destino(self):
        sql=self.sql_od('matriz migración interna por comunas de la región metropolitana')
        self.assertIn('CAST(FLOOR(origen / 1000) AS INTEGER) = 13',sql)
        self.assertIn('CAST(FLOOR(destino / 1000) AS INTEGER) = 13',sql)
        self.assertIn('origen <> destino',sql)

    def test_flujo_dirigido_filtra_ambos_roles(self):
        sql=self.sql_od('personas que vivían en Temuco en 2019 y ahora viven en Santiago')
        self.assertIn('origen = 9101',sql); self.assertIn('destino = 13101',sql)

    def test_porcentajes_ventana(self):
        sql=self.sql_od('matriz de migración interna entre comunas porcentaje por origen')
        self.assertIn('PARTITION BY origen',sql); self.assertIn('PARTITION BY destino',sql)

    def test_ranking_limit(self):
        sql=self.sql_od('20 principales flujos migratorios entre comunas')
        self.assertIn('LIMIT 20',sql)

    def test_inmigrantes_agrupan_destino(self):
        sql=self.sql_ind('inmigrantes internos por región')
        self.assertIn('SELECT destino AS codigo',sql); self.assertIn('origen <> destino',sql)

    def test_emigrantes_agrupan_origen(self):
        sql=self.sql_ind('emigrantes internos por región')
        self.assertIn('SELECT origen AS codigo',sql); self.assertIn('origen <> destino',sql)

    def test_saldo_suma_entradas_menos_salidas(self):
        sql=self.sql_ind('saldo migratorio interno por región')
        self.assertIn('SELECT destino AS codigo, COUNT(*) AS valor',sql)
        self.assertIn('SELECT origen AS codigo, -COUNT(*) AS valor',sql)

    def test_ambito_araucania_se_aplica_despues_de_flujos(self):
        sql=self.sql_ind('saldo migratorio interno por comuna de la región de la araucanía')
        self.assertIn('FROM indicador',sql)
        self.assertIn('FLOOR(codigo / 1000)',sql)
        self.assertIn('= 9',sql)

    def test_filtro_mujer_edad(self):
        sql=self.sql_od('matriz de migración interna de mujeres entre 20 y 39 años entre comunas')
        self.assertIn('p."sexo"',sql); self.assertIn("= '2'",sql)
        self.assertIn('TRY_CAST(p."edad" AS DOUBLE) >= 20',sql)
        self.assertIn('TRY_CAST(p."edad" AS DOUBLE) <= 39',sql)


if __name__=='__main__': unittest.main()
