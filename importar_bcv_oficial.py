#!/usr/bin/env python3
"""La serie oficial del BCV, de 2020 a hoy: el dólar y el euro de cada fecha valor.

El registrador (`registrar.py`) apunta el BCV desde el 2026-07-31, cuando empezó a
correr. Lo de antes sólo lo tiene el propio BCV, en su serie «Tipo de Cambio de
Referencia SMC»: un .xls por trimestre desde el primero de 2020, enlazados desde
`https://www.bcv.org.ve/estadisticas/tipo-cambio-de-referencia-smc`. Esto los lee
todos y escribe `historico/bcv-oficial.jsonl`, **una línea por fecha valor**, para
que la app enseñe el BCV de cualquier día.

Cómo es cada .xls, comprobado con el del tercer trimestre de 2026:

- **Una hoja por día de operación**, con su nombre (`08092026`), «Fecha Operacion»,
  «Fecha Valor» y, arriba a la derecha, una hora (`08/09/2026 06:18 PM`).
- **La tasa oficial es la venta (ASK) en bolívares** (la columna «Bs./M.E.»): la que
  enseña la portada del BCV. El dólar y el euro, en la misma hoja.
- **Las cifras son números del Excel, en coma flotante.** El BCV publica ocho
  decimales, así que cada una se redondea a ocho y se escribe como texto: nunca se
  publica un `float`.

Y lo que no es obvio:

- **Los enlaces se leen de la página, no se arman.** Un trimestre que el BCV vuelve
  a subir cambia de nombre (`2_1_2c23_smc_60.xls`), y el nombre de siempre sigue
  sirviendo una versión vieja a medias.
- **Hasta la fecha valor 2021-09-30 las cifras son de bolívares soberanos**: el
  2021-10-01 entró el bolívar digital, un millón de soberanos cada uno, y la primera
  fecha valor en digitales es la del 2021-10-04. Lo de antes se divide entre un
  millón, exacto, con `Decimal`, y la línea dice su escala y sus cifras originales.
- **La hora de la hoja se guarda tal cual, pero no se sabe qué hora es.** En julio-
  septiembre de 2026 va de las 3:36 de la tarde a las 10:44 de la noche, y nada dice
  si es la de publicación o la de cuando se armó el archivo. No dice desde cuándo
  rige una tasa: eso lo calcula quien la lee.

**Se puede volver a correr.** Las líneas que ya estaban no se tocan; se leen otra vez
sólo los trimestres desde el de la última fecha de operación que se tiene hasta el
de hoy, y entran las fechas valor nuevas. Si una que ya estaba sale ahora con otra
cifra, no se cambia nada y se dice: lo decide una persona.

**Si el BCV cambia la forma de la hoja, no se publica nada.** Cada hoja tiene que
tener sus dos fechas, la cabecera de siempre y el dólar y el euro como números; si
falta algo, sale un error que dice qué y dónde, y `historico/bcv-oficial.jsonl` se
queda como estaba. Una serie a medias o con una columna corrida es peor que ninguna.

Lee los .xls con `xlrd`, fijado con su huella en `requisitos-serie-oficial.txt`: es
el lector de .xls de siempre, en Python puro, sin fórmulas ni macros, y está
congelado como el formato. El registrador de cada media hora no lo necesita y sigue
sin nada de fuera.

Uso: `python3 importar_bcv_oficial.py`. Lo corre a mano el flujo
`.github/workflows/importar-bcv-oficial.yml`.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin

import xlrd

from registrar import CARACAS, FuenteCaida, _pedir_completando

RAIZ = Path(__file__).parent
SERIE = RAIZ / "historico" / "bcv-oficial.jsonl"

PAGINA = "https://www.bcv.org.ve/estadisticas/tipo-cambio-de-referencia-smc"
FUENTE = "bcv.org.ve (serie oficial)"

# El primer trimestre que publica el BCV: su primera hoja es la del 2020-03-27, con
# fecha valor 2020-03-30.
PRIMER_TRIMESTRE = (2020, 1)

# **La reconversión del 2021-10-01**: desde ese día, un bolívar digital son un millón
# de bolívares soberanos. Una fecha valor anterior está en soberanos.
RECONVERSION = date(2021, 10, 1)
DIGITOS_DE_LA_RECONVERSION = 6

ESCALA_SOBERANO = "bolívar soberano"
ESCALA_DIGITAL = "bolívar digital"

# El BCV publica ocho decimales.
OCHO_DECIMALES = Decimal("1e-8")

# **Cuánto puede separarse el euro de la cuenta del BCV.** El BCV saca el euro en
# bolívares multiplicando el dólar por la cotización del euro en dólares: el
# 2026-09-09, 820,1018 × 1,1633 = 954,02442394 exacto. Una diezmilésima de margen
# deja pasar cualquier redondeo y caza una fila equivocada (el yuan, el dólar de
# otro día), que se separaría en mucho más.
MARGEN_DEL_EURO = Decimal("1e-4")

# Lo más lejos que puede caer la fecha valor de la de operación: un fin de semana
# largo de Carnaval o de Semana Santa son cinco días. Más es una hoja que no se
# entiende.
DIAS_HASTA_LA_FECHA_VALOR = 10

# Entre una descarga y otra: es un organismo público y se le piden unas treinta.
PAUSA = 1.0

# Hasta cuántas páginas de enlaces se recorren: hoy son tres.
PAGINAS_MAXIMAS = 20

_ENLACE = re.compile(r"""href=["']([^"']*?2_1_2([a-d])(\d{2})_smc[^"'/]*\.xls)["']""", re.I)
_FECHA_OPERACION = re.compile(r"Fecha\s+Operaci[oó]n:\s*(\d{2})/(\d{2})/(\d{4})", re.I)
_FECHA_VALOR = re.compile(r"Fecha\s+Valor:\s*(\d{2})/(\d{2})/(\d{4})", re.I)
_HORA = re.compile(r"^(\d{2})/(\d{2})/(\d{4}) (\d{1,2}):(\d{2}) ([AP])\.?\s?M\.?$", re.I)

ASK = "Venta (ASK)"
BID = "Compra (BID)"
EN_BOLIVARES = "Bs./M.E."

# **El rótulo de la columna en bolívares**: «Bs./M.E.» en 2026, y con la «S» del bolívar soberano si una hoja
# vieja la escribiera (`Bs.S/M.E.`). Lo que importa es que sea la del bolívar y no la de otra moneda.
_ROTULO_EN_BOLIVARES = re.compile(r"^Bs\.?\s*S?\.?\s*/\s*M\.?\s*E\.?$", re.I)


class FormatoDelBcv(Exception):
    """Lo que publicó el BCV no tiene la forma de siempre: no se publica nada."""


class CambioEnLoPublicado(Exception):
    """Una fecha valor que ya estaba sale ahora con otra cifra: no se cambia nada."""


# ---------------------------------------------------------------------------
# LOS TRIMESTRES Y SUS ENLACES
# ---------------------------------------------------------------------------

Trimestre = tuple[int, int]


def trimestre_de(dia: date) -> Trimestre:
    return (dia.year, (dia.month - 1) // 3 + 1)


def trimestres(desde: Trimestre, hasta: Trimestre) -> list[Trimestre]:
    """Del trimestre `desde` al `hasta`, los dos incluidos."""
    salida = []
    a, t = desde
    while (a, t) <= hasta:
        salida.append((a, t))
        a, t = (a + 1, 1) if t == 4 else (a, t + 1)
    return salida


def enlaces_de_la_pagina(html: str) -> dict[Trimestre, str]:
    """Los .xls que enlaza una página de la serie, por trimestre.

    La letra es el trimestre (a, b, c, d) y las dos cifras, el año. **Si un trimestre
    sale dos veces, vale el primer enlace**: la página pone lo más nuevo arriba.
    """
    salida: dict[Trimestre, str] = {}
    for ruta, letra, anio in _ENLACE.findall(html):
        trimestre = (2000 + int(anio), "abcd".index(letra.lower()) + 1)
        salida.setdefault(trimestre, urljoin(PAGINA, ruta))
    return salida


def buscar_enlaces(pedir: Callable[[str], bytes], buscados: list[Trimestre]) -> dict[Trimestre, str]:
    """Recorre las páginas de la serie hasta tener el enlace de cada trimestre buscado.

    Se para cuando están todos, o cuando una página no trae ningún trimestre nuevo: la
    que pasa de la última sale vacía, y una que repitiera la anterior tampoco aporta.
    """
    encontrados: dict[Trimestre, str] = {}
    for n in range(PAGINAS_MAXIMAS):
        html = pedir(f"{PAGINA}?page={n}").decode("utf-8", errors="replace")
        nuevos = {t: u for t, u in enlaces_de_la_pagina(html).items() if t not in encontrados}
        if not nuevos:
            break
        encontrados.update(nuevos)
        if all(t in encontrados for t in buscados):
            break
        time.sleep(PAUSA)
    return encontrados


# ---------------------------------------------------------------------------
# UNA HOJA
# ---------------------------------------------------------------------------


def _fecha(m: re.Match) -> date:
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))


def cifra_exacta(valor, donde: str) -> Decimal:
    """Un número del Excel como la cifra que publica el BCV: redondeado a ocho decimales.

    El `float` del archivo es el número de ocho decimales que escribió el BCV, guardado
    en binario: 820,1018 se guarda como 820,10180000000002…, y redondearlo a ocho lo
    devuelve. Se hace con `Decimal` desde el valor exacto del `float`, sin pasar por
    su texto.
    """
    if isinstance(valor, bool) or not isinstance(valor, float) or not math.isfinite(valor) or valor <= 0:
        raise FormatoDelBcv(f"{donde}: «{valor!r}» no es una cifra positiva")
    with localcontext() as ctx:
        ctx.prec = 40
        return Decimal(valor).quantize(OCHO_DECIMALES, rounding=ROUND_HALF_EVEN)


def a_bolivares_de_hoy(cifra: Decimal, fecha_valor: date) -> tuple[Decimal, str]:
    """La cifra en bolívares digitales, y en qué escala estaba.

    Antes de la reconversión se corre la coma seis lugares: es dividir entre un millón
    sin redondear nada (4.138.617,5603 soberanos son 4,1386175603 digitales).
    """
    if fecha_valor < RECONVERSION:
        with localcontext() as ctx:
            ctx.prec = 40
            return cifra.scaleb(-DIGITOS_DE_LA_RECONVERSION), ESCALA_SOBERANO
    return cifra, ESCALA_DIGITAL


def _texto(d: Decimal) -> str:
    return format(d, "f")


def _celdas(hoja) -> list[list]:
    return [[hoja.cell_value(r, c) for c in range(hoja.ncols)] for r in range(hoja.nrows)]


def _una(patron: re.Pattern, celdas: list[list], que: str, donde: str) -> re.Match:
    vistas = {}
    for fila in celdas:
        for v in fila:
            if isinstance(v, str):
                m = patron.search(v)
                if m:
                    vistas[_fecha(m)] = m
    if not vistas:
        raise FormatoDelBcv(f"{donde}: no dice su {que}")
    if len(vistas) > 1:
        raise FormatoDelBcv(f"{donde}: dice dos {que}s distintas: {sorted(vistas)}")
    return next(iter(vistas.values()))


def _hora(celdas: list[list]) -> str | None:
    """La hora que estampa el BCV en la hoja, en hora de Caracas, o nada si no la trae."""
    for fila in celdas:
        for v in fila:
            if isinstance(v, str):
                m = _HORA.match(v.strip())
                if m:
                    d, mes, a, h, mi, ap = m.groups()
                    h = int(h) % 12 + (12 if ap.upper() == "P" else 0)
                    try:
                        return datetime(int(a), int(mes), int(d), h, int(mi), tzinfo=CARACAS).isoformat()
                    except ValueError:
                        return None
    return None


def _columnas(celdas: list[list], donde: str) -> tuple[int, int, int]:
    """Dónde está la cabecera y las dos columnas de venta: (fila, cotización en dólares, bolívares).

    La cabecera de siempre: «Compra (BID)», «Venta (ASK)» de la cotización en dólares,
    y otra vez las dos bajo «Bs./M.E.». La tasa oficial es la venta en bolívares, la
    de más a la derecha.
    """
    for r, fila in enumerate(celdas):
        textos = [v.strip() if isinstance(v, str) else "" for v in fila]
        if ASK not in textos:
            continue
        ventas = [c for c, t in enumerate(textos) if t == ASK]
        compras = [c for c, t in enumerate(textos) if t == BID]
        if len(ventas) != 2 or len(compras) != 2 or [compras[0] + 1, compras[1] + 1] != ventas:
            raise FormatoDelBcv(f"{donde}: la cabecera ya no es «{BID} | {ASK}» dos veces: {[t for t in textos if t]}")
        arriba = celdas[r - 1] if r > 0 else []
        rotulo = next((arriba[c].strip() for c in (compras[1], ventas[1]) if c < len(arriba) and isinstance(arriba[c], str) and arriba[c].strip()), "")
        if not _ROTULO_EN_BOLIVARES.match(rotulo):
            raise FormatoDelBcv(f"{donde}: sobre la segunda venta no dice «{EN_BOLIVARES}», sino «{rotulo}»")
        return r, ventas[0], ventas[1]
    raise FormatoDelBcv(f"{donde}: no tiene la columna «{ASK}»")


def _fila_de(celdas: list[list], desde: int, codigo: str, donde: str) -> list:
    filas = [f for f in celdas[desde + 1:] if any(isinstance(v, str) and v.strip() == codigo for v in f)]
    if len(filas) != 1:
        raise FormatoDelBcv(f"{donde}: tiene {len(filas)} filas de {codigo}, no una")
    return filas[0]


def es_hoja_de_un_dia(hoja) -> bool:
    """Si una hoja es de un día: dice alguna de sus dos fechas o trae la fila del dólar.

    Una que no tiene nada de eso (una portada, una de notas) no es de un día y se salta.
    Una que tiene algo, pero no todo, es una hoja que cambió, y la lee [linea_de_la_hoja]
    para decir qué le falta.
    """
    for fila in _celdas(hoja):
        for v in fila:
            if isinstance(v, str) and (_FECHA_VALOR.search(v) or _FECHA_OPERACION.search(v) or v.strip() == "USD"):
                return True
    return False


def linea_de_la_hoja(hoja, archivo: str) -> dict:
    """La línea de la serie que sale de la hoja de un día, sin `obtenido`."""
    donde = f"{archivo}, hoja «{hoja.name}»"
    celdas = _celdas(hoja)
    operacion = _fecha(_una(_FECHA_OPERACION, celdas, "fecha de operación", donde))
    valor = _fecha(_una(_FECHA_VALOR, celdas, "fecha valor", donde))
    if not 0 < (valor - operacion).days <= DIAS_HASTA_LA_FECHA_VALOR:
        raise FormatoDelBcv(f"{donde}: opera el {operacion} con fecha valor {valor}")

    cabecera, venta_en_dolares, venta_en_bolivares = _columnas(celdas, donde)
    dolar = _fila_de(celdas, cabecera, "USD", donde)
    euro = _fila_de(celdas, cabecera, "EUR", donde)

    def celda(fila: list, columna: int) -> object:
        return fila[columna] if columna < len(fila) else None

    usd = cifra_exacta(celda(dolar, venta_en_bolivares), f"{donde}, el dólar en bolívares")
    eur = cifra_exacta(celda(euro, venta_en_bolivares), f"{donde}, el euro en bolívares")
    if celda(dolar, venta_en_dolares) != 1.0:
        raise FormatoDelBcv(f"{donde}: la fila del dólar no vale un dólar ({celda(dolar, venta_en_dolares)!r})")
    cotizacion = cifra_exacta(celda(euro, venta_en_dolares), f"{donde}, el euro en dólares")
    with localcontext() as ctx:
        ctx.prec = 40
        if abs(eur - usd * cotizacion) > MARGEN_DEL_EURO * eur:
            raise FormatoDelBcv(f"{donde}: el euro ({eur}) no es el dólar ({usd}) por su cotización ({cotizacion})")

    ves_por_usd, escala = a_bolivares_de_hoy(usd, valor)
    ves_por_eur, _ = a_bolivares_de_hoy(eur, valor)
    linea = {
        "fecha_valor": valor.isoformat(),
        "fecha_operacion": operacion.isoformat(),
        "ves_por_usd": _texto(ves_por_usd),
        "ves_por_eur": _texto(ves_por_eur),
        "escala_original": escala,
    }
    if escala != ESCALA_DIGITAL:
        linea["cifras_originales"] = {"ves_por_usd": _texto(usd), "ves_por_eur": _texto(eur)}
    linea |= {"hora_de_la_hoja": _hora(celdas), "fuente": FUENTE, "archivo": archivo, "hoja": hoja.name}
    return linea


def lineas_del_libro(crudo: bytes, archivo: str) -> tuple[list[dict], list[str]]:
    """Las líneas de un .xls, y los nombres de las hojas que no son de un día."""
    try:
        libro = xlrd.open_workbook(file_contents=crudo)
    except Exception as e:  # noqa: BLE001 — cualquier cosa que no se pueda abrir es lo mismo aquí
        raise FormatoDelBcv(f"{archivo} no es un .xls que se pueda leer: {type(e).__name__}: {e}") from e
    lineas, saltadas = [], []
    for hoja in libro.sheets():
        if es_hoja_de_un_dia(hoja):
            lineas.append(linea_de_la_hoja(hoja, archivo))
        else:
            saltadas.append(f"{archivo}, hoja «{hoja.name}»")
    if not lineas:
        raise FormatoDelBcv(f"{archivo} no tiene ninguna hoja de un día")
    return lineas, saltadas


# ---------------------------------------------------------------------------
# LA SERIE
# ---------------------------------------------------------------------------


def leer_la_serie(ruta: Path) -> dict[str, tuple[str, dict]]:
    """Lo que ya se publicó: por fecha valor, la línea tal cual está escrita y lo que dice."""
    if not ruta.exists():
        return {}
    salida: dict[str, tuple[str, dict]] = {}
    for n, texto in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
        if not texto.strip():
            continue
        try:
            datos = json.loads(texto)
            fecha = date.fromisoformat(datos["fecha_valor"]).isoformat()
            date.fromisoformat(datos["fecha_operacion"])
            for clave in ("ves_por_usd", "ves_por_eur"):
                if not isinstance(datos[clave], str) or not Decimal(datos[clave]).is_finite():
                    raise ValueError(f"{clave} no es una cifra escrita como texto")
        except (ValueError, KeyError, TypeError, ArithmeticError) as e:
            raise FormatoDelBcv(f"{ruta.name}, línea {n}: no se entiende ({type(e).__name__}: {e})") from e
        if fecha in salida:
            raise FormatoDelBcv(f"{ruta.name}: la fecha valor {fecha} está dos veces")
        salida[fecha] = (texto, datos)
    return salida


def _mismas_cifras(a: dict, b: dict) -> bool:
    return all(Decimal(a[k]) == Decimal(b[k]) for k in ("ves_por_usd", "ves_por_eur"))


def juntar(ya: dict[str, tuple[str, dict]], nuevas: list[dict], obtenido: str) -> tuple[list[str], list[str]]:
    """La serie entera, en orden de fecha valor, y las fechas que entran ahora.

    **Lo que ya estaba se escribe igual**, byte a byte. Una fecha valor nueva entra con
    `obtenido`. Una que ya estaba con otra cifra es un [CambioEnLoPublicado]: no se
    escribe nada. Si el BCV trae la misma fecha valor en dos hojas, tienen que decir
    lo mismo.
    """
    vistas: dict[str, dict] = {}
    for linea in nuevas:
        fecha = linea["fecha_valor"]
        otra = vistas.get(fecha)
        if otra is not None and not _mismas_cifras(otra, linea):
            raise CambioEnLoPublicado(
                f"la fecha valor {fecha} sale en {otra['archivo']} «{otra['hoja']}» y en {linea['archivo']} «{linea['hoja']}» con cifras distintas"
            )
        vistas.setdefault(fecha, linea)
    cambios = []
    for fecha, linea in vistas.items():
        if fecha in ya and not _mismas_cifras(ya[fecha][1], linea):
            antes = ya[fecha][1]
            cambios.append(
                f"{fecha}: estaba {antes['ves_por_usd']} y {antes['ves_por_eur']}, y {linea['archivo']} dice ahora "
                f"{linea['ves_por_usd']} y {linea['ves_por_eur']}"
            )
    if cambios:
        raise CambioEnLoPublicado("el BCV cambió lo que ya se había publicado; no se toca nada:\n  " + "\n  ".join(cambios))
    entran = sorted(f for f in vistas if f not in ya)
    textos = {f: t for f, (t, _) in ya.items()}
    for f in entran:
        textos[f] = json.dumps(vistas[f] | {"obtenido": obtenido}, ensure_ascii=False)
    return [textos[f] for f in sorted(textos)], entran


def escribir(ruta: Path, lineas: list[str]) -> None:
    """Escribe la serie de una vez: o queda entera, o se queda como estaba."""
    ruta.parent.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=ruta.parent, delete=False, suffix=".tmp") as f:
        f.write("".join(t + "\n" for t in lineas))
        temporal = f.name
    os.replace(temporal, ruta)


def actualizar(
    ahora: datetime,
    pedir: Callable[[str], bytes] = _pedir_completando,
    ruta: Path = SERIE,
    primer_trimestre: Trimestre = PRIMER_TRIMESTRE,
) -> dict:
    """Lee lo que falta de la serie y la publica. Devuelve lo que pasó.

    La primera vez, todos los trimestres desde [primer_trimestre]. Después, desde el de
    la última fecha de operación que se tiene: así entra lo que faltaba de ése y lo de
    los siguientes, hasta el de hoy. **El trimestre de hoy puede no tener enlace
    todavía** —el BCV lo sube con su primera hoja—, y entonces se espera; cualquier otro
    que falte es un error.
    """
    ya = leer_la_serie(ruta)
    hoy = ahora.astimezone(CARACAS).date()
    operaciones = [date.fromisoformat(d["fecha_operacion"]) for _, d in ya.values()]
    desde = trimestre_de(max(operaciones)) if operaciones else primer_trimestre
    buscados = trimestres(desde, trimestre_de(hoy))
    enlaces = buscar_enlaces(pedir, buscados)

    nuevas: list[dict] = []
    saltadas: list[str] = []
    leidos: list[str] = []
    for trimestre in buscados:
        url = enlaces.get(trimestre)
        if url is None:
            if trimestre == trimestre_de(hoy):
                continue
            raise FormatoDelBcv(f"la página de la serie no enlaza el {trimestre[0]}, trimestre {trimestre[1]}")
        archivo = url.rsplit("/", 1)[-1]
        lineas, sin_dia = lineas_del_libro(pedir(url), archivo)
        nuevas.extend(lineas)
        saltadas.extend(sin_dia)
        leidos.append(archivo)
        time.sleep(PAUSA)

    obtenido = ahora.astimezone(timezone.utc).isoformat(timespec="seconds")
    serie, entran = juntar(ya, nuevas, obtenido)
    if entran:
        escribir(ruta, serie)
    fechas = sorted(json.loads(t)["fecha_valor"] for t in serie)
    return {
        "leidos": leidos,
        "entran": entran,
        "saltadas": saltadas,
        "dias": len(serie),
        "primera": fechas[0] if fechas else None,
        "ultima": fechas[-1] if fechas else None,
    }


def resumen(r: dict) -> str:
    lineas = [
        "## La serie oficial del BCV",
        "",
        f"- **{r['dias']} fechas valor**, del {r['primera']} al {r['ultima']}.",
        f"- Entran ahora **{len(r['entran'])}**" + (f": del {r['entran'][0]} al {r['entran'][-1]}." if r["entran"] else "."),
        f"- Archivos leídos ({len(r['leidos'])}): {', '.join(r['leidos']) or 'ninguno'}.",
    ]
    if r["saltadas"]:
        lineas.append(f"- Hojas que no son de un día, saltadas ({len(r['saltadas'])}): {'; '.join(r['saltadas'])}.")
    return "\n".join(lineas) + "\n"


def escribir_el_resumen(texto: str) -> None:
    """Lo dice en la salida y, en GitHub, en el resumen de la ejecución."""
    print(texto)
    destino = os.environ.get("GITHUB_STEP_SUMMARY")
    if destino:
        with open(destino, "a", encoding="utf-8") as f:
            f.write(texto + "\n")


def main() -> int:
    try:
        r = actualizar(datetime.now(timezone.utc))
    except (FormatoDelBcv, CambioEnLoPublicado, FuenteCaida) as e:
        escribir_el_resumen(f"## La serie oficial del BCV\n\n**No se publicó nada.** {type(e).__name__}: {e}\n")
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    escribir_el_resumen(resumen(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
