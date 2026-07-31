"""Pruebas de la lógica que decide y calcula, sin tocar la red.

Lo que se prueba aquí es justo lo que no se puede comprobar mirando: cuándo hay
que molestar al BCV y cuándo no, y cómo se calcula la tasa de mercado. Un error
en cualquiera de las dos no da error: da un número equivocado todos los días.
"""

import unittest
from datetime import datetime, timezone

from registrar import CARACAS, ANUNCIOS_DESCARTADOS, ANUNCIOS_USADOS, toca_mirar_bcv


def en_caracas(dia: int, hora: int) -> datetime:
    return datetime(2026, 7, dia, hora, 0, tzinfo=CARACAS).astimezone(timezone.utc)


class TestCuandoMirarElBCV(unittest.TestCase):
    """El BCV publica una vez al día. Preguntarle 48 veces es abusivo e inútil."""

    def test_en_la_ventana_de_publicacion_se_mira_siempre(self):
        # Entre las 3 y las 9 de la noche de Caracas: es cuando publican, con
        # margen, porque no siempre cumplen el horario.
        for hora in (15, 16, 17, 18, 19, 20):
            self.assertTrue(toca_mirar_bcv({}, en_caracas(31, hora)))

    def test_fuera_de_la_ventana_solo_en_horas_pares(self):
        self.assertTrue(toca_mirar_bcv({}, en_caracas(31, 8)))
        self.assertFalse(toca_mirar_bcv({}, en_caracas(31, 9)))
        self.assertTrue(toca_mirar_bcv({}, en_caracas(31, 22)))
        self.assertFalse(toca_mirar_bcv({}, en_caracas(31, 23)))

    def test_si_ya_publicaron_la_de_manana_se_deja_de_preguntar(self):
        # Ésta es la que ahorra las llamadas de verdad: en cuanto tenemos la
        # tasa con fecha posterior a hoy, no hay nada más que preguntar.
        ya = {"ves_por_usd_bcv": {"fecha_valor": "2026-08-01"}}
        self.assertFalse(toca_mirar_bcv(ya, en_caracas(31, 17)))
        self.assertFalse(toca_mirar_bcv(ya, en_caracas(31, 20)))

    def test_con_la_tasa_de_hoy_se_sigue_mirando_por_si_publican_la_de_manana(self):
        hoy = {"ves_por_usd_bcv": {"fecha_valor": "2026-07-31"}}
        self.assertTrue(toca_mirar_bcv(hoy, en_caracas(31, 17)))

    def test_una_fecha_ilegible_no_rompe_nada(self):
        roto = {"ves_por_usd_bcv": {"fecha_valor": "vaya usted a saber"}}
        self.assertTrue(toca_mirar_bcv(roto, en_caracas(31, 17)))


class TestTasaDeMercado(unittest.TestCase):
    """El primer anuncio de Binance es publicidad pagada y trae mal precio."""

    def test_se_descarta_el_primero_y_se_promedian_los_cinco_siguientes(self):
        # Números reales de una consulta del 31/07/2026.
        precios = [853.599, 851.0, 850.5, 850.35, 850.305, 850.222, 850.21]
        usados = precios[ANUNCIOS_DESCARTADOS:ANUNCIOS_DESCARTADOS + ANUNCIOS_USADOS]

        self.assertEqual(usados, [851.0, 850.5, 850.35, 850.305, 850.222])
        promedio = sum(usados) / len(usados)
        self.assertEqual(round(promedio, 4), 850.4754)
        # El anuncio pagado habría inflado la tasa un 0,37% todos los días.
        self.assertGreater(precios[0], promedio)


if __name__ == "__main__":
    unittest.main()
