# -*- coding: utf-8 -*-
import unittest
from pathlib import Path

from nl_parser import interpretar_consulta
from presentation import descripcion_cotidiana


class V38ParserTests(unittest.TestCase):
    def test_movilidad_laboral_por_region(self):
        i = interpretar_consulta("movilidad laboral por región")
        self.assertEqual(i["tipo_consulta"], "movilidad_laboral_fase3")
        self.assertEqual(i["movilidad_nivel"], "region")
        self.assertEqual(i["nivel_geografico"], "region")
        self.assertFalse(i["movilidad_incluir_diagonal"])
        self.assertIn(
            "región de residencia",
            descripcion_cotidiana(i),
        )

    def test_movilidad_regional_no_es_discapacidad(self):
        i = interpretar_consulta("movilidad laboral por región")
        self.assertEqual(i["variable"], "p44_lug_trab")
        self.assertNotEqual(i["variable"], "p32_caminar")


class V38FrontendStaticTests(unittest.TestCase):
    def test_frontend_tiene_cancelacion_esc(self):
        raiz = Path(__file__).resolve().parents[2]
        html = (raiz / "frontend" / "index.html").read_text(encoding="utf-8")
        self.assertIn("consultaAbortControllerV38", html)
        self.assertIn("/api/consulta/cancelar/", html)
        self.assertIn("event.key === 'Escape'", html)
        self.assertIn("edad_sexo_auxiliar_v38", html)


if __name__ == "__main__":
    unittest.main()
