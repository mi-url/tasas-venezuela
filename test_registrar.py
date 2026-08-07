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
    """El BCV publica una vez al día, entre las 4 y las 10 de la noche."""

    def test_en_la_ventana_de_publicacion_se_mira_siempre(self):
        # De 4 a 10 de la noche de Caracas. Dentro de esa franja no hay hora
        # fija, así que se mira en cada pasada.
        for hora in (16, 17, 18, 19, 20, 21):
            self.assertTrue(toca_mirar_bcv({}, en_caracas(31, hora)),
                            f"a las {hora} tiene que mirarse")

    def test_fuera_de_la_ventana_no_se_molesta(self):
        # Preguntar a las 3 de la tarde no descubre nada que no vaya a
        # descubrirse a las 4. Antes se preguntaba en todas las horas pares.
        for hora in (9, 10, 12, 14, 15, 22, 23):
            self.assertFalse(toca_mirar_bcv({}, en_caracas(31, hora)),
                             f"a las {hora} no hay nada que preguntar")

    def test_a_las_cinco_se_repesca_lo_que_falta(self):
        # La red de seguridad: si a las 5 de la mañana todavía falta la tasa
        # del día anterior, se publicó a deshora o nos quedamos sin máquina esa
        # tarde. Se mira otra vez.
        de_anteayer = {"ves_por_usd_bcv": {"fecha_valor": "2026-07-29"}}
        self.assertTrue(toca_mirar_bcv(de_anteayer, en_caracas(31, 5)))
        self.assertTrue(toca_mirar_bcv({}, en_caracas(31, 5)))

    def test_a_las_cinco_no_se_repesca_si_no_falta_nada(self):
        # Si anoche publicaron y la tenemos, la repesca no tiene qué recoger.
        # Sin esto, la red de seguridad se convierte en una consulta diaria de
        # más al servidor de un organismo público.
        de_hoy = {"ves_por_usd_bcv": {"fecha_valor": "2026-07-31"}}
        self.assertFalse(toca_mirar_bcv(de_hoy, en_caracas(31, 5)))

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
        # Y a las 5, una fecha que no se entiende se trata como que falta.
        self.assertTrue(toca_mirar_bcv(roto, en_caracas(31, 5)))


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
