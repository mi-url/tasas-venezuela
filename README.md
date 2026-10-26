# Tasas de cambio de Venezuela

Registro público y automático de a cuánto está el bolívar. Se actualiza solo cada media hora y guarda
el histórico, que es lo que ninguna fuente pública ofrece.

**Lo último está en [`tasas.json`](tasas.json).** El histórico, en [`historico/`](historico), un archivo
por mes con una línea por consulta.

## Qué publica

| Clave | Qué es | De dónde sale |
|---|---|---|
| `ves_por_usd_bcv` | El dólar oficial del Banco Central | la página del BCV, `bcv.org.ve` |
| `ves_por_eur_bcv` | El euro oficial, que muchos comercios usan | la página del BCV, en el mismo vistazo |
| `ves_por_usdt_mercado` | La tasa de la calle: lo que te dan por vender un USDT, y en `compra` lo que cuesta comprarlo | Binance P2P |
| `internacionales` | Divisas estándar contra el dólar | Banco Central Europeo, vía `frankfurter.dev` |
| `criptomonedas` | Bitcoin y USDT contra el dólar | CoinGecko |

USDT vale *casi* un dólar, y *casi* no es *exactamente*: darlo por supuesto arrastra un error pequeño en
cada operación que acaba sumando. Se pregunta y se guarda como cualquier otra tasa.

**Cada clave dice en qué unidad está.** `ves_por_usd` son bolívares por un dólar, no al revés. Puede
parecer pedante hasta que se mezclan las dos: confundirlas es lo que hace que un sistema registre una
ganancia de noventa mil dólares sobre diez.

**Ninguna cifra pasa por un número de coma flotante.** Cada una se guarda tal como la dio su fuente, con
todos sus decimales aunque traiga más de ocho. Sólo se redondea lo que se calcula aquí: la dispersión de
Binance y las inversas de las criptomonedas.

Y cada dato viene con **de dónde salió y cuándo**. Una tasa sin fecha es una tasa en la que no se puede
confiar.

## Desde cuándo rige una tasa del BCV

El BCV publica hacia las 4:30 de la tarde, a veces antes y a veces hacia las 5, y **lo que publica rige
desde ese momento hasta que publique la siguiente**. La del viernes rige el fin de semana y el lunes, y un
feriado bancario no publica: sigue la última.

Por eso cada publicación lleva, además de su `fecha_valor`, estas marcas. **Cada moneda lleva las suyas**:
el BCV a veces corrige sólo el euro, y entonces cambian las del euro y las del dólar se quedan como
estaban. Decir que el dólar «no estaba» a una hora en que ya estaba sería falso, y quien lo lee movería
desde cuándo rige.

| Campo | Qué es |
|---|---|
| `publicado_visto` | El momento en que el registrador la vio por primera vez: **desde cuándo rige** |
| `no_estaba_a_las` | La última vez que **la página** enseñaba la de antes. Entre las dos queda acotado cuándo publicó el BCV |
| `visto_por` | Quién la vio primero: `bcv.org.ve` o, si la página estaba caída, `dolarapi` |
| `respaldo` | `true` cuando la vio primero dolarapi: su `publicado_visto` es cuándo la dio dolarapi, que llega tarde, no cuándo publicó el BCV. Se mantiene hasta la publicación siguiente |
| `obtenido` | El momento de la lectura que trajo esa cifra. Volver a leer la misma no lo mueve |
| `consultado` | La última vez que se leyó la página. Una lectura de dolarapi no lo mueve |

`no_estaba_a_las` vacío quiere decir que no se sabe desde cuándo estaba. Pasa con la primera publicación
que recogió esta versión, porque la anterior no guardaba cuándo miraba. Si la página estuvo caída un
rato, el hueco entre `no_estaba_a_las` y `publicado_visto` es más largo, y es verdad: es lo que se sabe.

La `fecha_valor` no dice desde cuándo rige: sólo sirve para reconocer que salió una publicación nueva.

**Una cifra del BCV sin su coma decimal no se lee.** La página las escribe a la venezolana, `887,30200000`,
con punto de miles y coma decimal. Si un día la escribiera con punto decimal, quitarle los puntos de miles
la multiplicaría por cien millones; por eso una cifra que no tenga esa forma cuenta como página caída.

## Las decisiones que no son obvias

**El BCV se lee de su página, no de dolarapi.** dolarapi cambia a la tasa nueva a la medianoche de su
fecha valor, no cuando el BCV la publica: medido en septiembre de 2026, cada tasa nueva aparecía a las
5:23 de la mañana. Entre semana eso son unas siete horas y media tarde, y con un fin de semana de por
medio, días. dolarapi se queda de respaldo, sólo si la página no contesta, y **sólo cuenta si trae una
publicación de fecha posterior a la que ya se tiene**: con la misma fecha no trae nada nuevo (o es la
misma, o es una versión sin la corrección que la página ya dio), y con una anterior es una fuente
atrasada.

**Al BCV se le mira cada media hora desde las 3:30 de la tarde de Caracas, hasta que la página enseña la
nueva.** Que la diera dolarapi no cuenta: no dice cuándo publicó el BCV. Ya vista, se mira una vez más
después de las 10 de la noche por si la corrigió, y una vez por la mañana. Se empieza a las 3:30 y no a
las 4 porque el BCV a veces se adelanta. La página pesa 150 KB y es de un organismo público: se mira sólo
lo que hace falta.

**El certificado del BCV, sin apagar la seguridad.** Su servidor manda mal la cadena: el intermedio que
hace falta no es el que envía, y por eso Python no podía leer la página. En
[`certificados/intermedios-bcv.pem`](certificados/intermedios-bcv.pem) van los dos eslabones que faltan,
de Sectigo, y la cadena se verifica entera hasta una raíz de confianza del sistema. **Su certificado vence
el 2026-11-20**: si el nuevo lo firma otro intermedio que el servidor tampoco mande, el registrador lee
del propio certificado de dónde se baja, lo baja y lo añade, como hace un navegador. Lo bajado sólo
completa la cadena: la conexión sigue exigiendo una raíz de confianza.

**De Binance cuentan sólo los anuncios de una operación normal, y se usa la mediana.** Se piden los diez
primeros que aceptan unos 100 dólares en bolívares, calculados con la última tasa, y se toma la mediana.
Sin ese filtro salen anuncios que no son el precio de nadie: el 2026-10-25 el primero de un lado estaba a
980,54 con un límite de 300 a 400 bolívares, y los primeros del otro pedían mínimos de tres millones. La
mediana, además, no se mueve por un anuncio raro que se cuele arriba. Con el filtro, la venta salió
1.003,05 y el paralelo de dolarapi, 1.002,95.

**En la API de Binance, `tradeType` es lo que hace quien consulta.** `SELL` trae a quien compra USDT: es
lo que te dan por vender uno, que es la tasa de mercado. `BUY` trae a quien vende: lo que cuesta
comprarlo.

**Una fuente que falla no tumba a las demás.** Si una no contesta, contesta algo que no es lo esperado
o revienta por algo que nadie previó, se repite su dato anterior **con su hora de entonces** y se apunta
en `fallos`; las otras se publican igual. Una pasada tiene además un tope de tres minutos y medio para
consultar, para que GitHub no la corte sin publicar nada. La alarma está en la app, que dice de cuándo es
cada tasa.

## Por qué existe esto

Porque **ninguna fuente guarda el histórico**. Si nadie anota la tasa de cada día, el día que tu teléfono
esté apagado esa tasa se pierde para siempre, y las operaciones de esa fecha ya no se pueden valorar bien.

Y porque una sola consulta compartida es mejor que muchas: si cada app preguntara por su cuenta,
multiplicaríamos las llamadas por cada usuario, y el endpoint de Binance —que no es oficial— acabaría
bloqueándonos. Leer un archivo publicado, en cambio, no tiene límite.

## Cuánto cuesta

Nada. Corre en GitHub Actions, en un repositorio público y con las máquinas normales de GitHub, que no se
cobran. Son unas 48 pasadas de medio minuto al día, y nada se queda encendido esperando.

## Cómo se usa

```
https://raw.githubusercontent.com/mi-url/tasas-venezuela/main/tasas.json
```

Quien lo consuma debería **decir en pantalla de cuándo es cada tasa**. El servicio anterior estuvo seis
meses sirviendo una tasa de 339 bolívares cuando el dólar estaba en 746, y nadie se enteró porque nada
mostraba la fecha. Ése es el fallo que no se puede repetir.

## Correrlo a mano

```bash
python3 registrar.py                     # consulta y actualiza los archivos
python3 -m unittest test_registrar -v    # las pruebas, con respuestas reales guardadas en pruebas/
```

Sin dependencias: sólo la librería estándar de Python.
