#!/usr/bin/env python3
"""Contrasta `historico/bcv-oficial.jsonl` con lo que guardó el registrador y con frankfurter.

Dos testigos que no salen del mismo sitio que la serie:

- **El registrador** (`historico/AAAA-MM.jsonl`): lo que vio cada media hora desde el
  2026-07-31, de la página del BCV o de dolarapi.
- **frankfurter** (`api.frankfurter.dev`), que lee los mismos .xls del BCV por su
  cuenta desde el 2021-10-04 y devuelve cada cifra como número; aquí se redondea a
  ocho decimales, como hace la serie.

Dice cuántas fechas valor coinciden, dólar y euro, cuáles no y cuáles faltan en cada
lado. **No cambia nada ni decide nada**: es para que una persona lo lea. Lo corre el
flujo `importar-bcv-oficial.yml` después de importar, y se puede correr a mano.

Uso: `python3 contrastar_bcv_oficial.py [--sin-frankfurter]`.
"""

from __future__ import annotations

import json
import os
import sys
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

from registrar import FuenteCaida, _pedir

RAIZ = Path(__file__).parent
SERIE = RAIZ / "historico" / "bcv-oficial.jsonl"
HISTORICO = RAIZ / "historico"

DESDE_FRANKFURTER = "2021-10-04"
FRANKFURTER = "https://api.frankfurter.dev/v2/rates?base={base}&quotes=VES&providers=BCV&from={desde}&to={hasta}"
OCHO = Decimal("1e-8")
MONEDAS = {"USD": "ves_por_usd", "EUR": "ves_por_eur"}


def la_serie(ruta: Path = SERIE) -> dict[str, dict]:
    return {d["fecha_valor"]: d for d in (json.loads(t) for t in ruta.read_text(encoding="utf-8").splitlines() if t.strip())}


def del_registrador(carpeta: Path = HISTORICO) -> dict[str, dict[str, set[Decimal]]]:
    """Por fecha valor y moneda, todas las cifras del BCV que vio el registrador (una corrección son dos)."""
    salida: dict[str, dict[str, set[Decimal]]] = {}
    for ruta in sorted(carpeta.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9].jsonl")):
        for texto in ruta.read_text(encoding="utf-8").splitlines():
            if not texto.strip():
                continue
            foto = json.loads(texto)
            for moneda, (bloque, cifra) in {"USD": ("ves_por_usd_bcv", "ves_por_usd"), "EUR": ("ves_por_eur_bcv", "valor")}.items():
                b = foto.get(bloque) or {}
                if b.get("fecha_valor") and b.get(cifra):
                    salida.setdefault(b["fecha_valor"], {}).setdefault(moneda, set()).add(Decimal(str(b[cifra])))
    return salida


def de_frankfurter(desde: str, hasta: str, pedir=_pedir) -> dict[str, dict[str, Decimal]]:
    salida: dict[str, dict[str, Decimal]] = {}
    for moneda in MONEDAS:
        crudo = json.loads(pedir(FRANKFURTER.format(base=moneda, desde=desde, hasta=hasta)), parse_float=Decimal)
        for fila in crudo:
            cifra = Decimal(str(fila["rate"])).quantize(OCHO, rounding=ROUND_HALF_EVEN)
            salida.setdefault(fila["date"], {})[moneda] = cifra
    return salida


def contrastar(serie: dict[str, dict], testigo: dict[str, dict], nombre: str, desde: str | None = None) -> list[str]:
    """Las líneas del contraste con un testigo, sobre las fechas que cubre."""
    def coincide(fecha: str, moneda: str) -> bool:
        visto = testigo[fecha].get(moneda)
        if visto is None:
            return False
        cifra = Decimal(serie[fecha][MONEDAS[moneda]])
        return cifra in visto if isinstance(visto, set) else cifra == visto

    fechas_testigo = {f for f in testigo if desde is None or f >= desde}
    ultima = max(serie) if serie else ""
    comunes = sorted(f for f in serie if f in fechas_testigo)
    iguales = [f for f in comunes if all(coincide(f, m) for m in MONEDAS)]
    distintas = [f for f in comunes if f not in iguales]
    solo_serie = sorted(f for f in serie if (desde is None or f >= desde) and f not in fechas_testigo
                        and (not fechas_testigo or min(fechas_testigo) <= f <= max(fechas_testigo)))
    solo_testigo = sorted(f for f in fechas_testigo if f not in serie and f <= ultima)
    lineas = [f"### Contra {nombre}", ""]
    if comunes:
        lineas.append(f"- **{len(iguales)} de {len(comunes)} fechas valor coinciden**, dólar y euro, del {comunes[0]} al {comunes[-1]}.")
    else:
        lineas.append("- No hay fechas valor en común.")
    for f in distintas[:20]:
        t = testigo[f]
        lineas.append(f"  - {f}: la serie dice {serie[f]['ves_por_usd']} y {serie[f]['ves_por_eur']}; {nombre}, {t.get('USD')} y {t.get('EUR')}")
    if solo_serie:
        lineas.append(f"- En la serie y no en {nombre} ({len(solo_serie)}): {', '.join(solo_serie[:30])}")
    if solo_testigo:
        lineas.append(f"- En {nombre} y no en la serie ({len(solo_testigo)}): {', '.join(solo_testigo[:30])}")
    return lineas + [""]


def main() -> int:
    serie = la_serie()
    lineas = ["## Contraste de la serie oficial del BCV", ""]
    lineas += contrastar(serie, del_registrador(), "el registrador")
    if "--sin-frankfurter" not in sys.argv:
        try:
            lineas += contrastar(serie, de_frankfurter(DESDE_FRANKFURTER, max(serie)), "frankfurter", DESDE_FRANKFURTER)
        except (FuenteCaida, ValueError, KeyError, TypeError) as e:
            lineas += ["### Contra frankfurter", "", f"- No se pudo traer: {e}", ""]
    texto = "\n".join(lineas)
    print(texto)
    destino = os.environ.get("GITHUB_STEP_SUMMARY")
    if destino:
        with open(destino, "a", encoding="utf-8") as f:
            f.write(texto + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
