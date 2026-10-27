"""Las pruebas de la serie oficial del BCV, con lo que publicó el BCV de verdad.

Las respuestas de `pruebas/respuestas/` son reales y no se tocaron:

- `bcv-serie-oficial-2026-09-09.html`: la primera página de la serie, como la sirvió
  el BCV el 2026-09-09 a las 13:01 UTC;
- `bcv-serie-oficial-2_1_2c26_smc.xls`: el .xls del tercer trimestre de 2026 bajado
  en ese mismo momento, con las hojas del 1 de julio al 8 de septiembre;
- `frankfurter-bcv-usd-2026-T3.json` y `frankfurter-bcv-eur-2026-T3.json`: lo que
  contestó frankfurter el 2026-10-27 para esas fechas.

Las dos primeras las grabó frankfurter (`lineofflight/frankfurter`,
`spec/vcr_cassettes/bcv.yml`): desde fuera de Venezuela no siempre se llega al BCV.
Y lo que esto compara con el registrador es su propio histórico real, el de
`historico/`.

**Lo que no ha pasado todavía se prueba sobre una hoja real cambiada**, y cada prueba
dice qué le cambió: el cambio de escala de 2021 y un BCV que cambia la forma de la
hoja. Las cifras del 29/09/2021 son las que guarda de ese día bolivar-flow, y las del
04/10/2021, las de frankfurter.

Ninguna prueba sale a internet.
"""

import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

import xlrd

import contrastar_bcv_oficial as contraste
import importar_bcv_oficial as serie
from importar_bcv_oficial import CambioEnLoPublicado, FormatoDelBcv

RAIZ = Path(__file__).parent
RESPUESTAS = RAIZ / "pruebas" / "respuestas"
PAGINA = (RESPUESTAS / "bcv-serie-oficial-2026-09-09.html").read_bytes()
LIBRO = (RESPUESTAS / "bcv-serie-oficial-2_1_2c26_smc.xls").read_bytes()
URL_DEL_LIBRO = "https://www.bcv.org.ve/sites/default/files/EstadisticasGeneral/2_1_2c26_smc.xls"

# Cuando se grabó: el miércoles 9 de septiembre de 2026, a las 9:01 de la mañana de Caracas.
GRABADO = datetime(2026, 9, 9, 13, 1, 32, tzinfo=timezone.utc)


class HojaCambiada:
    """Una hoja real de `xlrd` con algunas celdas cambiadas, y con otro nombre si se quiere."""

    def __init__(self, hoja, celdas=None, nombre=None):
        self._hoja = hoja
        self._celdas = celdas or {}
        self.name = nombre or hoja.name
        self.nrows = hoja.nrows
        self.ncols = hoja.ncols

    def cell_value(self, r, c):
        return self._celdas.get((r, c), self._hoja.cell_value(r, c))


class LibroCambiado:
    def __init__(self, libro, hojas):
        self._hojas = hojas

    def sheets(self):
        return self._hojas


def el_libro():
    return xlrd.open_workbook(file_contents=LIBRO)


def la_hoja(nombre):
    return el_libro().sheet_by_name(nombre)


class LaRed:
    """Contesta con lo grabado: la primera página y el .xls del tercer trimestre de 2026.

    Las demás páginas salen vacías, como la que pasa de la última. `libros` cambia lo
    que se sirve en una dirección, y `pagina`, la primera página. Apunta lo que se pide.
    """

    def __init__(self, pagina=PAGINA, libros=None):
        self.pagina = pagina
        self.libros = {URL_DEL_LIBRO: LIBRO} if libros is None else libros
        self.pedidos = []

    def __call__(self, url):
        self.pedidos.append(url)
        if url.startswith(serie.PAGINA):
            return self.pagina if url.endswith("?page=0") else b"<html><body></body></html>"
        if url in self.libros:
            return self.libros[url]
        raise AssertionError(f"nadie esperaba {url}")

    @property
    def libros_pedidos(self):
        return [u.rsplit("/", 1)[-1] for u in self.pedidos if not u.startswith(serie.PAGINA)]


class SinPausa(unittest.TestCase):
    def setUp(self):
        parche = mock.patch.object(serie, "PAUSA", 0)
        parche.start()
        self.addCleanup(parche.stop)
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.ruta = Path(carpeta.name) / "bcv-oficial.jsonl"

    def correr(self, red=None, ahora=GRABADO, primer_trimestre=(2026, 3)):
        return serie.actualizar(ahora, red or LaRed(), self.ruta, primer_trimestre=primer_trimestre)

    def lineas(self):
        return [json.loads(t) for t in self.ruta.read_text(encoding="utf-8").splitlines()]

    def por_fecha(self):
        return {d["fecha_valor"]: d for d in self.lineas()}


class ElLibroReal(SinPausa):
    def test_una_linea_por_fecha_valor_del_1_de_julio_al_8_de_septiembre(self):
        r = self.correr()
        self.assertEqual(r["dias"], 49)
        fechas = [d["fecha_valor"] for d in self.lineas()]
        self.assertEqual(fechas, sorted(fechas))
        self.assertEqual((fechas[0], fechas[-1]), ("2026-07-02", "2026-09-09"))
        # El viernes 24 de julio fue feriado: la hoja del jueves 23 opera para el lunes 27.
        self.assertNotIn("2026-07-24", fechas)
        self.assertEqual(self.por_fecha()["2026-07-27"]["fecha_operacion"], "2026-07-23")

    def test_la_linea_del_9_de_septiembre_entera(self):
        self.correr()
        self.assertEqual(
            self.por_fecha()["2026-09-09"],
            {
                "fecha_valor": "2026-09-09",
                "fecha_operacion": "2026-09-08",
                "ves_por_usd": "820.10180000",
                "ves_por_eur": "954.02442394",
                "escala_original": "bolívar digital",
                "hora_de_la_hoja": "2026-09-08T18:18:00-04:00",
                "fuente": "bcv.org.ve (serie oficial)",
                "archivo": "2_1_2c26_smc.xls",
                "hoja": "08092026",
                "obtenido": "2026-09-09T13:01:32+00:00",
            },
        )

    def test_ninguna_cifra_es_un_numero_de_coma_flotante(self):
        self.correr()
        texto = self.ruta.read_text(encoding="utf-8")
        for d in self.lineas():
            for clave in ("ves_por_usd", "ves_por_eur"):
                self.assertIsInstance(d[clave], str)
                self.assertRegex(d[clave], r"^\d+\.\d{8}$")
        self.assertNotIn("820.1018,", texto)

    def test_cada_numero_del_xls_es_uno_de_ocho_decimales(self):
        # Lo que se escribe tiene que ser el mismo número que guardó el BCV: redondeado a ocho decimales y vuelto a
        # leer como float, es el mismo float. Si no, la hoja traería más de ocho decimales y redondear perdería algo.
        for hoja in el_libro().sheets():
            for r in range(hoja.nrows):
                for c in range(hoja.ncols):
                    v = hoja.cell_value(r, c)
                    if isinstance(v, float):
                        self.assertEqual(float(serie.cifra_exacta(v, "")), v, f"{hoja.name} {r},{c}")

    def test_la_cifra_es_la_del_bcv_y_no_la_del_float(self):
        self.assertEqual(serie.cifra_exacta(820.1018, ""), Decimal("820.10180000"))
        self.assertNotEqual(Decimal(820.1018), Decimal("820.1018"), "el float no es exacto: por eso se redondea")
        with self.assertRaises(FormatoDelBcv):
            serie.cifra_exacta("820,1018", "")
        with self.assertRaises(FormatoDelBcv):
            serie.cifra_exacta(0.0, "")

    def test_la_hora_de_la_hoja_es_la_de_caracas_y_no_decide_nada(self):
        self.correr()
        d = self.por_fecha()["2026-07-09"]
        self.assertEqual(d["hora_de_la_hoja"], "2026-07-08T22:44:00-04:00")
        self.assertNotIn("publicado_visto", d)


class ElEuro(SinPausa):
    def test_es_la_venta_en_bolivares_de_la_misma_hoja(self):
        self.correr()
        d = self.por_fecha()["2026-09-09"]
        # En la hoja: 1,16328 y 1,1633 dólares por euro, y 951,63936288 y 954,02442394 bolívares (compra y venta).
        self.assertEqual(d["ves_por_eur"], "954.02442394")

    def test_es_el_dolar_por_su_cotizacion(self):
        self.correr()
        for d in self.lineas():
            self.assertGreater(Decimal(d["ves_por_eur"]), Decimal(d["ves_por_usd"]), d["fecha_valor"])

    def test_si_la_fila_del_euro_no_cuadra_con_el_dolar_no_se_publica(self):
        # La hoja real del 8 de septiembre con el euro de otro día (el del 1 de julio): una fila corrida.
        hoja = HojaCambiada(la_hoja("08092026"), {(10, 6): 728.48086846})
        with self.assertRaisesRegex(FormatoDelBcv, "el euro .* no es el dólar"):
            serie.linea_de_la_hoja(hoja, "2_1_2c26_smc.xls")


class LaEscalaDe2021(SinPausa):
    """**El cambio de escala**, sobre las hojas reales del 7 y el 8 de septiembre de 2026 con las fechas y las cifras
    de los dos días de alrededor de la reconversión: la fecha valor 29/09/2021, todavía en soberanos, y la del
    04/10/2021, la primera en digitales. Entre las dos no hubo publicación."""

    def hoja_del_29(self):
        return HojaCambiada(
            la_hoja("08092026"),
            {
                (0, 6): "28/09/2021 05:31 PM",
                (4, 1): "Fecha Operacion: 28/09/2021",
                (4, 3): "Fecha Valor: 29/09/2021",
                (10, 4): 1.16757,
                (10, 6): 4832125.70487947,
                (14, 6): 4138617.5603,
            },
            nombre="28092021",
        )

    def hoja_del_4(self):
        return HojaCambiada(
            la_hoja("07092026"),
            {
                (0, 6): "01/10/2021 05:02 PM",
                (4, 1): "Fecha Operacion: 01/10/2021",
                (4, 3): "Fecha Valor: 04/10/2021",
                (10, 4): 1.16142,
                (10, 6): 4.85680506,
                (14, 6): 4.18178183,
            },
            nombre="01102021",
        )

    def test_lo_de_antes_del_2021_10_01_se_divide_entre_un_millon_exacto(self):
        d = serie.linea_de_la_hoja(self.hoja_del_29(), "2_1_2c21_smc.xls")
        self.assertEqual(d["ves_por_usd"], "4.13861756030000")
        self.assertEqual(d["ves_por_eur"], "4.83212570487947")
        self.assertEqual(d["escala_original"], "bolívar soberano")
        self.assertEqual(d["cifras_originales"], {"ves_por_usd": "4138617.56030000", "ves_por_eur": "4832125.70487947"})

    def test_lo_de_despues_queda_como_esta(self):
        d = serie.linea_de_la_hoja(self.hoja_del_4(), "2_1_2d21_smc.xls")
        self.assertEqual(d["ves_por_usd"], "4.18178183")
        self.assertEqual(d["ves_por_eur"], "4.85680506")
        self.assertEqual(d["escala_original"], "bolívar digital")
        self.assertNotIn("cifras_originales", d)

    def test_las_dos_quedan_en_la_misma_escala(self):
        antes = Decimal(serie.linea_de_la_hoja(self.hoja_del_29(), "a")["ves_por_usd"])
        despues = Decimal(serie.linea_de_la_hoja(self.hoja_del_4(), "b")["ves_por_usd"])
        self.assertLess(abs(despues / antes - 1), Decimal("0.02"), "sin dividir, el salto sería de un millón de veces")

    def test_la_frontera_es_el_1_de_octubre(self):
        cifra = Decimal("4138617.56030000")
        self.assertEqual(serie.a_bolivares_de_hoy(cifra, date(2021, 9, 30)), (Decimal("4.13861756030000"), "bolívar soberano"))
        self.assertEqual(serie.a_bolivares_de_hoy(cifra, date(2021, 10, 1)), (cifra, "bolívar digital"))

    def test_dividir_no_redondea_nada(self):
        cifra = Decimal("77893.46050000")
        digital, _ = serie.a_bolivares_de_hoy(cifra, date(2020, 3, 30))
        self.assertEqual(digital * 1_000_000, cifra)
        self.assertEqual(format(digital, "f"), "0.07789346050000")


class UnTrimestreResubido(SinPausa):
    """El BCV vuelve a subir un trimestre con otro nombre (`2_1_2c23_smc_60.xls`), y el de siempre sigue sirviendo una
    versión vieja. La página real, con el del tercer trimestre de 2026 resubido."""

    RESUBIDO = URL_DEL_LIBRO.replace("_smc.xls", "_smc_60.xls")

    def pagina_resubida(self):
        return PAGINA.replace(b"2_1_2c26_smc.xls", b"2_1_2c26_smc_60.xls")

    def test_los_enlaces_se_leen_de_la_pagina(self):
        enlaces = serie.enlaces_de_la_pagina(PAGINA.decode("utf-8"))
        self.assertEqual(sorted(enlaces), [(2024, 2), (2024, 3), (2024, 4), (2025, 1), (2025, 2), (2025, 3), (2025, 4), (2026, 1), (2026, 2), (2026, 3)])
        self.assertEqual(enlaces[(2026, 3)], URL_DEL_LIBRO)

    def test_se_baja_el_que_enlaza_la_pagina_y_no_el_de_siempre(self):
        red = LaRed(pagina=self.pagina_resubida(), libros={self.RESUBIDO: LIBRO})
        self.correr(red)
        self.assertEqual(red.libros_pedidos, ["2_1_2c26_smc_60.xls"])
        self.assertEqual({d["archivo"] for d in self.lineas()}, {"2_1_2c26_smc_60.xls"})

    def test_si_el_trimestre_sale_dos_veces_vale_el_primero(self):
        html = '<a href="/f/2_1_2c26_smc_60.xls">nuevo</a> <a href="/f/2_1_2c26_smc.xls">viejo</a>'
        self.assertTrue(serie.enlaces_de_la_pagina(html)[(2026, 3)].endswith("_60.xls"))

    def test_un_trimestre_sin_enlace_que_no_es_el_de_hoy_es_un_error(self):
        red = LaRed(pagina=PAGINA.replace(b"2_1_2b26_smc.xls", b"otro.pdf"))
        with self.assertRaisesRegex(FormatoDelBcv, "no enlaza el 2026, trimestre 2"):
            self.correr(red, primer_trimestre=(2026, 2))
        self.assertFalse(self.ruta.exists())

    def test_el_trimestre_de_hoy_sin_enlace_todavia_se_espera(self):
        # El 2026-10-27 la página grabada en septiembre todavía no enlaza el cuarto trimestre.
        r = self.correr(ahora=datetime(2026, 10, 27, 12, tzinfo=timezone.utc))
        self.assertEqual(r["leidos"], ["2_1_2c26_smc.xls"])
        self.assertEqual(r["dias"], 49)


class CoincideConElRegistrador(SinPausa):
    """Lo que sale del .xls contra lo que apuntó el registrador cada media hora en `historico/2026-07.jsonl`,
    `2026-08.jsonl` y `2026-09.jsonl`: del 31 de julio, su primer día, al 9 de septiembre."""

    def test_agosto_y_septiembre_coinciden_dolar_y_euro(self):
        self.correr()
        oficial = self.por_fecha()
        visto = contraste.del_registrador(RAIZ / "historico")
        comunes = sorted(f for f in oficial if f in visto)
        self.assertEqual((comunes[0], comunes[-1], len(comunes)), ("2026-07-31", "2026-09-09", 29))
        for f in comunes:
            self.assertIn(Decimal(oficial[f]["ves_por_usd"]), visto[f]["USD"], f)
            self.assertIn(Decimal(oficial[f]["ves_por_eur"]), visto[f]["EUR"], f)
        self.assertIn("29 de 29 fechas valor coinciden", "\n".join(contraste.contrastar(oficial, visto, "el registrador")))

    def test_y_con_frankfurter_las_cuarenta_y_nueve(self):
        self.correr()

        def pedir(url):
            moneda = "usd" if "base=USD" in url else "eur"
            return (RESPUESTAS / f"frankfurter-bcv-{moneda}-2026-T3.json").read_bytes()

        frank = contraste.de_frankfurter("2026-07-02", "2026-09-09", pedir)
        texto = "\n".join(contraste.contrastar(self.por_fecha(), frank, "frankfurter"))
        self.assertIn("49 de 49 fechas valor coinciden", texto)

    def test_el_contraste_dice_lo_que_no_coincide(self):
        oficial = {"2026-09-09": {"ves_por_usd": "820.10180000", "ves_por_eur": "954.02442394"}}
        texto = "\n".join(contraste.contrastar(oficial, {"2026-09-09": {"USD": Decimal("820.1"), "EUR": Decimal("954.02442394")}}, "otro"))
        self.assertIn("0 de 1", texto)
        self.assertIn("2026-09-09: la serie dice 820.10180000", texto)


class SiElBcvCambiaLaHoja(SinPausa):
    """Una hoja que cambió no publica nada, y dice qué le pasa. Sobre la hoja real del 8 de septiembre de 2026."""

    def falla(self, celdas, patron):
        with self.assertRaisesRegex(FormatoDelBcv, patron):
            serie.linea_de_la_hoja(HojaCambiada(la_hoja("08092026"), celdas), "2_1_2c26_smc.xls")

    def test_sin_la_venta(self):
        self.falla({(8, 6): "Venta"}, "la cabecera ya no es")

    def test_sin_la_cabecera(self):
        self.falla({(8, 4): "", (8, 6): ""}, "no tiene la columna «Venta \\(ASK\\)»")

    def test_con_otra_moneda_sobre_las_columnas(self):
        self.falla({(7, 5): "US$/M.E."}, "no dice «Bs./M.E.»")

    def test_con_la_s_del_bolivar_soberano_sigue_siendo_el_bolivar(self):
        d = serie.linea_de_la_hoja(HojaCambiada(la_hoja("08092026"), {(7, 5): "Bs.S/M.E."}), "2_1_2c26_smc.xls")
        self.assertEqual(d["ves_por_usd"], "820.10180000")

    def test_sin_la_fecha_valor(self):
        self.falla({(4, 3): "Fecha: 09/09/2026"}, "no dice su fecha valor")

    def test_con_la_fecha_valor_antes_de_la_operacion(self):
        self.falla({(4, 3): "Fecha Valor: 07/09/2026"}, "opera el 2026-09-08 con fecha valor 2026-09-07")

    def test_con_el_dolar_escrito_como_texto(self):
        self.falla({(14, 6): "820,1018"}, "no es una cifra positiva")

    def test_sin_la_fila_del_dolar(self):
        self.falla({(14, 1): "US"}, "tiene 0 filas de USD")

    def test_con_la_fila_del_dolar_que_no_vale_un_dolar(self):
        self.falla({(14, 4): 6.711}, "no vale un dólar")

    def test_una_hoja_sin_nada_de_un_dia_se_salta_y_se_dice(self):
        vacia = HojaCambiada(la_hoja("08092026"), {(r, c): "" for r in range(41) for c in range(7)}, nombre="Notas")
        with mock.patch.object(serie.xlrd, "open_workbook", return_value=LibroCambiado(None, [vacia, la_hoja("07092026")])):
            lineas, saltadas = serie.lineas_del_libro(LIBRO, "2_1_2c26_smc.xls")
        self.assertEqual([d["fecha_valor"] for d in lineas], ["2026-09-08"])
        self.assertEqual(saltadas, ["2_1_2c26_smc.xls, hoja «Notas»"])

    def test_y_la_serie_que_ya_estaba_se_queda_igual(self):
        self.correr()
        antes = self.ruta.read_bytes()
        # Un día después, el BCV cambió una hoja del mismo trimestre: le quitó la venta.
        hojas = [HojaCambiada(h, {(8, 6): "Venta"}) if h.name == "08092026" else h for h in el_libro().sheets()]
        with mock.patch.object(serie.xlrd, "open_workbook", return_value=LibroCambiado(None, hojas)):
            with self.assertRaises(FormatoDelBcv):
                self.correr(ahora=datetime(2026, 9, 10, 13, tzinfo=timezone.utc))
        self.assertEqual(self.ruta.read_bytes(), antes)

    def test_un_archivo_que_no_es_un_xls(self):
        red = LaRed(libros={URL_DEL_LIBRO: b"<html>Mantenimiento</html>"})
        with self.assertRaisesRegex(FormatoDelBcv, "no es un .xls que se pueda leer"):
            self.correr(red)
        self.assertFalse(self.ruta.exists())


class VolverACorrer(SinPausa):
    def test_otra_vez_no_cambia_ni_un_byte_y_solo_lee_el_trimestre_en_curso(self):
        self.correr()
        antes = self.ruta.read_bytes()
        red = LaRed()
        # Con la serie ya escrita, el primer trimestre no cuenta: se empieza en el de su última fecha de operación.
        r = self.correr(red, ahora=datetime(2026, 9, 9, 22, tzinfo=timezone.utc), primer_trimestre=(2024, 2))
        self.assertEqual(r["entran"], [])
        self.assertEqual(self.ruta.read_bytes(), antes)
        self.assertEqual(red.libros_pedidos, ["2_1_2c26_smc.xls"])

    def test_la_primera_vez_lee_todos_los_trimestres_desde_el_primero(self):
        red = LaRed(libros={})
        with self.assertRaises(FormatoDelBcv):
            serie.actualizar(GRABADO, red, self.ruta)
        # Buscó el primer trimestre de 2020 en todas las páginas antes de decir que falta.
        self.assertEqual(sum(u.startswith(serie.PAGINA) for u in red.pedidos), 2)

    def test_entran_las_fechas_nuevas_y_lo_de_antes_no_se_toca(self):
        self.correr()
        todas = self.ruta.read_text(encoding="utf-8").splitlines()
        # Como si la última vez hubiera sido el viernes 4: hasta la fecha valor del 7, y con otro `obtenido`.
        viejas = [t.replace("2026-09-09T13:01:32+00:00", "2026-09-04T23:00:00+00:00") for t in todas[:-2]]
        self.ruta.write_text("".join(t + "\n" for t in viejas), encoding="utf-8")
        r = self.correr()
        self.assertEqual(r["entran"], ["2026-09-08", "2026-09-09"])
        ahora = self.ruta.read_text(encoding="utf-8").splitlines()
        self.assertEqual(ahora[:-2], viejas, "las líneas que ya estaban, byte a byte")
        self.assertEqual(json.loads(ahora[-1])["obtenido"], "2026-09-09T13:01:32+00:00")

    def test_una_fecha_que_ya_estaba_con_otra_cifra_no_cambia_nada_y_se_dice(self):
        self.correr()
        texto = self.ruta.read_text(encoding="utf-8").replace('"ves_por_usd": "820.10180000"', '"ves_por_usd": "820.10170000"')
        self.ruta.write_text(texto, encoding="utf-8")
        with self.assertRaisesRegex(CambioEnLoPublicado, "2026-09-09: estaba 820.10170000"):
            self.correr()
        self.assertEqual(self.ruta.read_text(encoding="utf-8"), texto)

    def test_la_misma_fecha_valor_en_dos_hojas_tiene_que_decir_lo_mismo(self):
        dos = [la_hoja("08092026"), HojaCambiada(la_hoja("08092026"), {(14, 6): 820.2, (10, 6): 954.14069}, nombre="copia")]
        with mock.patch.object(serie.xlrd, "open_workbook", return_value=LibroCambiado(None, dos)):
            with self.assertRaisesRegex(CambioEnLoPublicado, "con cifras distintas"):
                self.correr()

    def test_una_serie_que_no_se_entiende_no_se_pisa(self):
        self.correr()
        buena = self.ruta.read_text(encoding="utf-8").splitlines()[0]
        for mala, motivo in [
            ("esto no es json", "JSONDecodeError"),
            ('{"fecha_valor": "2026-09-09", "ves_por_usd": "820.1018", "ves_por_eur": "954.02442394"}', "fecha_operacion"),
            (buena.replace('"639.70290000"', "639.7029"), "no es una cifra escrita como texto"),
        ]:
            texto = f"{buena}\n{mala}\n"
            self.ruta.write_text(texto, encoding="utf-8")
            with self.assertRaisesRegex(FormatoDelBcv, f"línea 2: no se entiende .*{motivo}"):
                self.correr()
            self.assertEqual(self.ruta.read_text(encoding="utf-8"), texto)


if __name__ == "__main__":
    unittest.main()
