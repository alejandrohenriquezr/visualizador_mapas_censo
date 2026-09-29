# -*- coding: utf-8 -*-
import sys
import types
import unittest
from pathlib import Path

from nl_parser import interpretar_consulta

try:
    import duckdb  # noqa: F401
except ModuleNotFoundError:
    sys.modules['duckdb'] = types.SimpleNamespace(connect=lambda *a, **k: None)
import data_engine  # noqa: E402


class V30RegresionesTests(unittest.TestCase):
    def setUp(self):
        self.original = data_engine._ruta_parquet
        data_engine._ruta_parquet = lambda tabla: Path(f'C:/tmp/{tabla}.parquet')

    def tearDown(self):
        data_engine._ruta_parquet = self.original

    def test_migracion_rm_restringe_matriz_completa(self):
        i = interpretar_consulta('matriz migración interna por comunas de la región metropolitana')
        self.assertEqual(int(i['migracion_region_origen_codigo']), 13)
        self.assertEqual(int(i['migracion_region_destino_codigo']), 13)
        sql, _ = data_engine._construir_sql_migracion_interna_od(i)
        self.assertIn('CAST(FLOOR(origen / 1000) AS INTEGER) = 13', sql)
        self.assertIn('CAST(FLOOR(destino / 1000) AS INTEGER) = 13', sql)

    def test_movilidad_laboral_no_incluye_diagonal_por_defecto(self):
        i = interpretar_consulta('movilidad laboral región Metropolitana')
        self.assertFalse(i['movilidad_incluir_diagonal'])
        self.assertEqual(int(i['movilidad_region_origen_codigo']), 13)
        self.assertEqual(int(i['movilidad_region_destino_codigo']), 13)
        sql, _ = data_engine._construir_sql_movilidad_laboral_fase3(i)
        self.assertIn('origen <> destino', sql)

    def test_movilidad_laboral_respeta_inclusion_explicita(self):
        i = interpretar_consulta('matriz de movilidad laboral entre comunas incluyendo la misma comuna')
        self.assertTrue(i['movilidad_incluir_diagonal'])
        sql, _ = data_engine._construir_sql_movilidad_laboral_fase3(i)
        self.assertNotIn('origen <> destino', sql)


if __name__ == '__main__':
    unittest.main()
