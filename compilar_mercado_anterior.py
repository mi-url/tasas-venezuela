#!/usr/bin/env python3
"""El mercado de antes del registrador: una cifra por día, del 2020-03-30 al 2026-07-30.

El registrador (`registrar.py`) mide el mercado desde el 2026-07-31, cuando empezó
a correr. Lo de antes no lo midió nadie de aquí: esto lo recopila **una sola vez**
de cuatro fuentes públicas y escribe `historico/mercado-anterior.jsonl`, una línea
por día, para que la app enseñe el mercado de cualquier día desde el primero de la
serie oficial del BCV. **El archivo queda congelado**: no lo corre ningún flujo.
Volver a correrlo sólo hace falta si se decide cambiar la recopilación, y entonces
se revisa la diferencia línea a línea antes de publicarla.

**Una cifra por día, y cada una dice de qué fuente es.** Nunca se mezclan dos en
una cifra ni se corrige una con otra: el día que la primera fuente no tiene, se
toma la siguiente, tal cual. Lo que dicen las demás ese día va al lado, como
`testigos`, para que se pueda comparar.

**Qué fuente manda cada día** ([TRAMOS]), elegido midiendo cuál se parece más al
mercado de la app. Ese mercado es el que mide hoy el registrador, la mediana de diez
anuncios de Binance P2P, que casa con el paralelo de dolarapi: el 26 de octubre de
2026, lectura a lectura, a un 0,03 %, y en el promedio de ese día y del siguiente, a
menos de un 0,3 %. Por eso el árbitro es ese paralelo, que dolarapi guarda desde el
2026-02-14:

- **Del 2020-03-30 al 2025-05-27, el paralelo de xjp.cl** (`Parallel_Daily_Full.csv`,
  el cierre de cada día hábil, CC BY 4.0), que es el de DolarToday y EnParaleloVzla. El
  día que no lo tiene, el de Monitor Dólar que anota Wikipedia (CC BY-SA 4.0), que en
  2020 sale de media un 1 % por debajo. Los fines de semana no se publicaba, y quedan
  sin cifra: no se rellenan con otra fuente que mide otra cosa, porque cada lunes daría
  un salto que no fue del mercado.
- **Del 2025-05-28 al 2025-10-27, «Dólar Binance» de CriptoDólar**, una foto diaria de
  Binance P2P hacia las 7 de la tarde de Caracas, y si falta, Wikipedia. Ese día el
  paralelo dejó de publicarse: xjp.cl repite el 142,42 del 27 ocho días hábiles más, y
  luego otras cifras semanas enteras, y lo que quedó como mercado fue Binance P2P.
- **Del 2025-10-28 al 2026-07-30, Yadio** (`hist/365`): el promedio de 24 horas de cada
  día, todos los días; sus días son los de UTC, de 8 de la noche a 8 de la noche de
  Caracas. Contra el árbitro, de febrero a julio de 2026, sale un 0,36 % por debajo y
  nunca a más de un 3,6 %. CriptoDólar, en cambio, un 1,84 % por encima, con 15 días a
  más de un 5 %: una foto a una hora no es el promedio del día cuando el mercado se
  mueve. Si a Yadio le falta un día, xjp.cl o Wikipedia.

**Las dos costuras con el registrador no son del mercado.** Su método de antes del
2026-10-26 salía un 1,75 % por encima de Yadio: el 2026-07-31 sube eso de golpe, y el
2026-10-26 baja otro tanto al cambiar de método. La app dice de qué fuente y de qué
método es cada día.

Se probó y se descartó **LocalBitcoins** para 2020-2021 (la tasa que se deduce de
UsefulTulips): sale un 2-3 % por debajo de los dos paralelos, y su costura con xjp.cl
sería un salto que no fue del mercado. **2020 es aproximado en todas**: con la
hiperinflación el paralelo se movía hasta un 10 % en un día, y xjp.cl y Wikipedia lo
anotan a horas distintas.

**Las cifras se escriben como texto exacto**, en bolívares de hoy:

- **Lo que viene en bolívares soberanos se divide entre un millón**, corriendo la
  coma con `Decimal`, sin redondear: todo lo de xjp.cl, que nunca aplicó la
  reconversión de 2021, y lo de Wikipedia de antes del 2021-10-01. La línea dice su
  escala y su cifra original.
- **Lo que viene como número binario** (CriptoDólar, Yadio) se redondea a ocho
  decimales, como la serie oficial del BCV: quita el ruido de la coma flotante y no
  cambia nada que se vea.

**Las erratas se quitan, no se corrigen**, y no se usan ni como testigo:

- **Las que se ven solas**: una cifra que se separa más de un 12 % de la anterior y de
  la siguiente de su misma fuente, cuando esas dos casan entre sí a menos de un 6 %.
  Son cuatro, conocidas ([ERRATAS]): si aparece otra, no se publica nada y se dice cuál.
- **Las que esa regla no ve**, cada una comprobada contra todas las demás fuentes
  ([ERRATAS_A_MANO]): dos de Wikipedia en la reconversión de 2021, seguidas, y una de
  xjp.cl en diciembre de 2020, cuyas vecinas se separan un 6,3 %.

Y **lo que no se lee sin dudar, no se lee** ([cifra_de_wikipedia]): dos celdas de
Wikipedia escriben `8 88` y `24 80`, con un espacio por coma, y se quedan sin leer.

Uso: `python3 compilar_mercado_anterior.py <carpeta de las fuentes>`, con los cuatro
archivos de [ARCHIVOS] tal como se bajaron, sin tocarlos.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

RAIZ = Path(__file__).parent
SALIDA = RAIZ / "historico" / "mercado-anterior.jsonl"
CARACAS = timezone(timedelta(hours=-4))

# El primer día de la serie oficial del BCV, y el día antes del primero del registrador.
DESDE = date(2020, 3, 30)
HASTA = date(2026, 7, 30)
RECONVERSION = date(2021, 10, 1)

XJP = "xjp.cl (paralelo)"
WIKIPEDIA = "es.wikipedia (paralelo)"
CRIPTODOLAR = "criptodolar.net (Binance P2P)"
YADIO = "yadio.io"

ARCHIVOS = {
    # https://xjp.cl/Parallel_Daily_Full.csv
    XJP: "xjp-Parallel_Daily_Full.csv",
    # https://es.wikipedia.org/wiki/Anexo:Cotización_histórica_del_bolívar_con_respecto_al_dólar,
    # revisión 175956434 (2026-10-23), su texto fuente.
    WIKIPEDIA: "wikipedia-anexo-cotizacion-historica-del-bolivar.wikitext",
    # https://exchange.vcoud.com/coins/dolar-binance?gap=5y&base=usd (lo que lee criptodolar.net)
    CRIPTODOLAR: "criptodolar-dolar-binance-5y.json",
    # https://api.yadio.io/hist/365/VES
    YADIO: "yadio-hist-365-VES.json",
}

# Desde qué día manda qué orden de fuentes: la primera que tenga el día.
TRAMOS = [
    (DESDE, [XJP, WIKIPEDIA]),
    (date(2025, 5, 28), [CRIPTODOLAR, WIKIPEDIA]),
    (date(2025, 10, 28), [YADIO, XJP, WIKIPEDIA]),
]

# Las erratas que se ven solas: la fuente y el día, comprobadas a mano contra las otras.
ERRATAS = {
    (XJP, "2020-06-10"),  # 260.513 soberanos entre 198.402 y 210.033
    (XJP, "2020-11-09"),  # 344.602 entre 540.024 y 564.932
    (WIKIPEDIA, "2025-11-21"),  # 248,57 entre 348,73 y 354,84; xjp.cl, CriptoDólar y Yadio, unos 345
    (WIKIPEDIA, "2026-06-12"),  # 510,30 entre 806,30 y 790,08; las otras tres, unos 800
}

# Las que la regla no ve, comprobadas contra todas las demás fuentes:
ERRATAS_A_MANO = {
    # 5.035.381 soberanos y 5,14: el Monitor Dólar de la reconversión, que el anexo cita, un 18-20 % por encima de
    # todo lo demás (xjp.cl, 4,26 el 29 y 4,17 el 5; el BCV, 4,14 y 4,18), y que al día hábil siguiente vuelve a 4,19.
    # Dos seguidas: la regla, que mira las vecinas, no las ve.
    (WIKIPEDIA, "2021-09-30"),
    (WIKIPEDIA, "2021-10-01"),
    # 1.226.312 soberanos entre 1.135.133 y 1.068.023, con Wikipedia en 1,0506, LocalBitcoins en 1,0250 y el BCV en
    # 1,1034: un 18 % por encima de las demás. Sus vecinas se separan un 6,3 %, y la regla pide menos de un 6.
    (XJP, "2020-12-15"),
}

SALTO_DE_ERRATA = Decimal("0.12")
VECINAS_QUE_CASAN = Decimal("0.06")
UN_MILLON = 6
OCHO_DECIMALES = Decimal("0.00000001")


class Cifra:
    """Una cifra de una fuente: en bolívares de hoy, y como la escribió la fuente si estaba en soberanos."""

    def __init__(self, valor: Decimal, original: str | None = None):
        self.valor = valor
        self.original = original


# --- Las fuentes ------------------------------------------------------------


def de_soberanos(texto: str) -> Cifra:
    return Cifra(Decimal(texto).scaleb(-UN_MILLON), texto)


def binario(numero: float) -> Decimal:
    return Decimal(repr(numero)).quantize(OCHO_DECIMALES, rounding=ROUND_HALF_EVEN)


def leer_xjp(ruta: Path) -> dict[str, Cifra]:
    """El cierre de cada día, en soberanos: el archivo nunca aplicó la reconversión de 2021."""
    salida = {}
    with ruta.open(newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            mes, dia, anio = fila["<DATE>"].split("/")
            salida[date(int(anio), int(mes), int(dia)).isoformat()] = de_soberanos(fila["<CLOSE>"])
    return salida


MESES = {"ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
         "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12}


def _celda(texto: str) -> str:
    """El texto de una celda, sin citas, plantillas ni etiquetas, y sin «Bs.». Los espacios de los miles quedan, como
    un espacio normal: hacen falta para leer el número sin adivinar."""
    t = re.sub(r"<ref[^>/]*/>", "", texto)
    t = re.sub(r"<ref[^>]*>.*?</ref>", "", t, flags=re.S)
    t = re.sub(r"\{\{.*?\}\}", "", t, flags=re.S)
    t = re.sub(r"<[^>]+>", "", t)
    for espacio in ("&thinsp;", "&nbsp;", "\u2009", "\u00a0"):
        t = t.replace(espacio, " ")
    for basura in ("B/s.", "Bs.S", "Bs.", "Bs"):
        t = t.replace(basura, "")
    return re.sub(r"\s+", " ", t).strip()


def cifra_de_wikipedia(texto: str) -> str | None:
    """Un número escrito a mano, como texto exacto con punto decimal. **Lo que no se lee sin dudar, no se lee**:
    `99.999` puede ser noventa y nueve mil o noventa y nueve con tres decimales, y `8 88` no es ocho mil ochenta y
    ocho —los miles van de tres en tres— sino, seguramente, 8,88 con un espacio por coma. Ninguno de los dos se lee."""
    if re.fullmatch(r"\d+", texto):
        return texto
    if m := re.fullmatch(r"(\d+)[.,](\d{1,2})", texto):
        return f"{m.group(1)}.{m.group(2)}"
    if m := re.fullmatch(r"(\d{1,3}(?: \d{3})+)(?:[.,](\d{1,2}))?", texto):
        entero = m.group(1).replace(" ", "")
        return f"{entero}.{m.group(2)}" if m.group(2) else entero
    return None


def _columnas(fila: str) -> list[str]:
    """**Las columnas de una fila**, con cada celda de `colspan="N"` puesta como N columnas: la primera con su texto y
    las demás vacías. Así, un mes sin ese día no corre a los de su derecha. Los atributos van antes de la primera `|`
    de la celda, y a veces con una comilla sin cerrar (`style="background:DarkSlateBlue |`)."""
    columnas = []
    for celda in fila.strip().lstrip("|!").split("||"):
        if m := re.match(r'\s*colspan\s*=\s*"?(\d+)"?', celda):
            contenido = celda.split("|", 1)[1] if "|" in celda else ""
            columnas += [contenido] + [""] * (int(m.group(1)) - 1)
        else:
            columnas.append(celda)
    return columnas


def leer_wikipedia(ruta: Path) -> tuple[dict[str, Cifra], list[tuple[str, str]]]:
    """Las tablas «Tabla cambiaria diaria AAAA» del anexo, su columna del paralelo. Devuelve también lo que no se
    pudo leer como número, para decirlo.

    Cada tabla tiene una fila con los meses («MES DE ENERO»), que dice en qué columnas va cada uno —tres, o cuatro
    cuando lleva un «Promedio €»—, y otra con lo que es cada columna («DÍA», «BCV», «PARALELO»): el día es la
    primera de su mes, y el paralelo, la suya."""
    texto = ruta.read_text(encoding="utf-8")
    salida: dict[str, Cifra] = {}
    raras = []
    for seccion in re.finditer(r"==\s*Tabla cambiaria diaria (\d{4})\s*==(.*?)(?=\n==[^=])", texto, flags=re.S):
        anio = int(seccion.group(1))
        # Por mes: (mes, su primera columna, cuántas tiene, la del paralelo).
        meses: list[tuple[int | None, int, int, int]] = []
        for fila in seccion.group(2).split("\n|-"):
            # Una fila acaba donde acaba su tabla: lo que sigue a `|}` es texto suelto, o la tabla siguiente.
            trozo = fila.split("\n|}")[0]
            columnas = _columnas(" ".join(trozo.split("\n")))
            if any(re.search(r"MES DE\s+[A-ZÁÉÍÓÚ]+", c) for c in columnas):
                meses, desde = [], 0
                for celda in trozo.replace("\n", " ").strip().lstrip("|!").split("||"):
                    ancho = int(m.group(1)) if (m := re.match(r'\s*colspan\s*=\s*"?(\d+)"?', celda)) else 1
                    if nombre := re.search(r"MES DE\s+([A-ZÁÉÍÓÚ]+)", celda):
                        meses.append((MESES.get(nombre.group(1).upper()), desde, ancho, desde + 2))
                    desde += ancho
                continue
            if not meses:
                continue
            nombres = [_celda(c).upper() for c in columnas]
            if "DÍA" in nombres:
                meses = [
                    (mes, desde, ancho, next((desde + k for k in range(ancho) if nombres[desde + k:desde + k + 1] == ["PARALELO"]), desde + 2))
                    for mes, desde, ancho, _ in meses
                ]
                continue
            for mes, desde, ancho, paralelo in meses:
                if mes is None or paralelo >= len(columnas) or not _celda(columnas[desde]).isdigit():
                    continue
                try:
                    dia = date(anio, mes, int(_celda(columnas[desde])))
                except ValueError:
                    continue
                clave = dia.isoformat()
                if clave in salida:
                    continue
                crudo = _celda(columnas[paralelo])
                cifra = cifra_de_wikipedia(crudo)
                if cifra is None:
                    if re.search(r"\d", crudo):
                        raras.append((clave, crudo))
                    continue
                salida[clave] = de_soberanos(cifra) if dia < RECONVERSION else Cifra(Decimal(cifra))
    return salida, raras


def leer_criptodolar(ruta: Path) -> dict[str, Cifra]:
    """Una foto por día de Caracas; si un día tiene dos, la última."""
    fotos = sorted(json.loads(ruta.read_text(encoding="utf-8"))["prices"], key=lambda p: p["createdAt"])
    salida = {}
    for p in fotos:
        cuando = datetime.fromisoformat(p["createdAt"].replace("Z", "+00:00")).astimezone(CARACAS)
        salida[cuando.date().isoformat()] = Cifra(binario(p["price"]))
    return salida


def leer_yadio(ruta: Path) -> dict[str, Cifra]:
    salida = {}
    for r in json.loads(ruta.read_text(encoding="utf-8")):
        mes, dia, anio = r["date"].split("/")
        salida[f"{anio}-{mes}-{dia}"] = Cifra(binario(r["rate"]))
    return salida


# --- Las erratas ------------------------------------------------------------


def erratas_de(fuente: str, serie: dict[str, Cifra]) -> set[tuple[str, str]]:
    dias = sorted(d for d in serie if (DESDE - timedelta(days=10)).isoformat() <= d <= (HASTA + timedelta(days=10)).isoformat())
    salida = set()
    for antes, dia, despues in zip(dias, dias[1:], dias[2:]):
        a, b, c = serie[antes].valor, serie[dia].valor, serie[despues].valor
        if abs(b / a - 1) > SALTO_DE_ERRATA and abs(b / c - 1) > SALTO_DE_ERRATA and abs(a / c - 1) < VECINAS_QUE_CASAN:
            salida.add((fuente, dia))
    return salida


# --- La recopilación --------------------------------------------------------


def _texto(d: Decimal) -> str:
    return format(d, "f")


def recopilar(series: dict[str, dict[str, Cifra]], obtenido: dict[str, str]) -> list[dict]:
    lineas = []
    dia = DESDE
    while dia <= HASTA:
        clave = dia.isoformat()
        orden = next(o for desde, o in reversed(TRAMOS) if dia >= desde)
        elegida = next((f for f in orden if clave in series[f]), None)
        if elegida is not None:
            cifra = series[elegida][clave]
            linea = {"fecha": clave, "ves_por_usd": _texto(cifra.valor), "fuente": elegida}
            if cifra.original is not None:
                linea["escala_original"] = "bolívar soberano"
                linea["cifra_original"] = cifra.original
            testigos = {f: _texto(series[f][clave].valor) for f in series if f != elegida and clave in series[f]}
            if testigos:
                linea["testigos"] = testigos
            linea["obtenido"] = obtenido[elegida]
            lineas.append(linea)
        dia += timedelta(days=1)
    return lineas


def obtenido_de(ruta: Path) -> str:
    """Cuándo se bajó: la hora del archivo, que se copió sin tocar."""
    return datetime.fromtimestamp(ruta.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat()


def main(carpeta: Path) -> int:
    rutas = {f: carpeta / nombre for f, nombre in ARCHIVOS.items()}
    wikipedia, raras = leer_wikipedia(rutas[WIKIPEDIA])
    series = {
        XJP: leer_xjp(rutas[XJP]),
        WIKIPEDIA: wikipedia,
        CRIPTODOLAR: leer_criptodolar(rutas[CRIPTODOLAR]),
        YADIO: leer_yadio(rutas[YADIO]),
    }
    halladas = set().union(*(erratas_de(f, s) for f, s in series.items()))
    if halladas != ERRATAS:
        print("Las erratas no son las conocidas; no se publica nada.", file=sys.stderr)
        print("  nuevas:", sorted(halladas - ERRATAS), "· ya no están:", sorted(ERRATAS - halladas), file=sys.stderr)
        return 1
    faltan = sorted(e for e in ERRATAS_A_MANO if e[1] not in series[e[0]])
    if faltan:
        print("Erratas a mano que ya no están en su fuente; no se publica nada:", faltan, file=sys.stderr)
        return 1
    for fuente, dia in ERRATAS | ERRATAS_A_MANO:
        del series[fuente][dia]
    lineas = recopilar(series, {f: obtenido_de(r) for f, r in rutas.items()})
    SALIDA.parent.mkdir(exist_ok=True)
    SALIDA.write_text("".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lineas), encoding="utf-8")
    total = (HASTA - DESDE).days + 1
    print(f"{len(lineas)} días con cifra de {total}; {total - len(lineas)} sin cifra.")
    for f in series:
        print(f"  {f}: {sum(1 for l in lineas if l['fuente'] == f)}")
    dentro = [r for r in raras if DESDE.isoformat() <= r[0] <= HASTA.isoformat()]
    if dentro:
        print("  celdas de Wikipedia que no se leyeron:", dentro)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Uso: python3 compilar_mercado_anterior.py <carpeta de las fuentes>")
    sys.exit(main(Path(sys.argv[1])))
