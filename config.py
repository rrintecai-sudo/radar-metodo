"""
config.py — El método de Alejandro Cardona, traducido a parámetros.

Todo lo que en los documentos es una "regla" o un "número" vive AQUÍ, en un solo
lugar, para que sea fácil de leer y de afinar sin tocar el motor. Si mañana
descubrimos (con nuestra propia bitácora) que un número funciona mejor con otro
valor, se cambia aquí y todo el sistema lo respeta.

Referencias: guia_fundacional_metodo.docx / estrategias_compendio_profundo.docx
"""

# ---------------------------------------------------------------------------
# 1) LOS ACTIVOS — solo estos cinco al principio (Guía, secc. 4 y 5)
# ---------------------------------------------------------------------------
# "al principio, SOLO estos. Nada de acciones individuales de moda hasta que
#  dominemos el método con los índices."
ACTIVOS = {
    "SPY": {"nombre": "S&P 500 (ETF)",       "clase": "indice"},
    "QQQ": {"nombre": "Nasdaq 100 (ETF)",    "clase": "indice"},
    "GLD": {"nombre": "Oro (ETF)",           "clase": "materia_prima"},
    "SLV": {"nombre": "Plata (ETF)",         "clase": "materia_prima"},
    "USO": {"nombre": "Petróleo (ETF)",      "clase": "materia_prima"},
}
TICKERS = list(ACTIVOS.keys())

# ---------------------------------------------------------------------------
# 1b) UNIVERSO AMPLIADO — acciones individuales líquidas con buenas opciones
# ---------------------------------------------------------------------------
# Cardona también opera acciones. Aquí ampliamos las oportunidades a nombres muy
# líquidos, con opciones semanales, que se MUEVEN fuerte (más movimiento del
# activo = más ganancia en la opción -> el "beneficio grande" del método).
# Se puede editar libremente: agregar/quitar tickers según lo que esté rentable.
#
# OJO: las acciones traen riesgo de empresa única (earnings, noticias). Por eso
# el motor vigila la fecha de resultados de cada una (ver engine/earnings.py).
# Cada acción: nombre, índice ("SP500" = dentro del S&P 500 = núcleo del método;
# "FUERA" = fuera del S&P 500 = motor paralelo, más potencial pero más riesgo) y sector.
# Membresía verificada el 2026-07-13 contra la lista oficial del S&P 500 (503 miembros).
STOCKS = {
    # --- NÚCLEO: dentro del S&P 500 (el principio del método: solo estas) ---
    "AAPL": {"nombre": "Apple", "indice": "SP500", "sector": "Tecnología"},
    "MSFT": {"nombre": "Microsoft", "indice": "SP500", "sector": "Tecnología"},
    "NVDA": {"nombre": "Nvidia", "indice": "SP500", "sector": "Tecnología"},
    "AMZN": {"nombre": "Amazon", "indice": "SP500", "sector": "Consumo"},
    "GOOGL": {"nombre": "Alphabet", "indice": "SP500", "sector": "Comunicaciones"},
    "META": {"nombre": "Meta", "indice": "SP500", "sector": "Comunicaciones"},
    "AVGO": {"nombre": "Broadcom", "indice": "SP500", "sector": "Tecnología"},
    "TSLA": {"nombre": "Tesla", "indice": "SP500", "sector": "Consumo"},
    "NFLX": {"nombre": "Netflix", "indice": "SP500", "sector": "Comunicaciones"},
    "AMD": {"nombre": "AMD", "indice": "SP500", "sector": "Tecnología"},
    "MU": {"nombre": "Micron", "indice": "SP500", "sector": "Tecnología"},
    "SMCI": {"nombre": "Super Micro", "indice": "SP500", "sector": "Tecnología"},
    "QCOM": {"nombre": "Qualcomm", "indice": "SP500", "sector": "Tecnología"},
    "MRVL": {"nombre": "Marvell", "indice": "SP500", "sector": "Tecnología"},
    "INTC": {"nombre": "Intel", "indice": "SP500", "sector": "Tecnología"},
    "COIN": {"nombre": "Coinbase", "indice": "SP500", "sector": "Financieras"},
    "PLTR": {"nombre": "Palantir", "indice": "SP500", "sector": "Tecnología"},
    "UBER": {"nombre": "Uber", "indice": "SP500", "sector": "Industriales"},
    "CRWD": {"nombre": "CrowdStrike", "indice": "SP500", "sector": "Tecnología"},
    "ADBE": {"nombre": "Adobe", "indice": "SP500", "sector": "Tecnología"},
    "CRM": {"nombre": "Salesforce", "indice": "SP500", "sector": "Tecnología"},
    "NOW": {"nombre": "ServiceNow", "indice": "SP500", "sector": "Tecnología"},
    "BA": {"nombre": "Boeing", "indice": "SP500", "sector": "Industriales"},
    "DIS": {"nombre": "Disney", "indice": "SP500", "sector": "Comunicaciones"},
    "JPM": {"nombre": "JPMorgan", "indice": "SP500", "sector": "Financieras"},
    "XOM": {"nombre": "Exxon", "indice": "SP500", "sector": "Energía"},
    # --- PARALELO: fuera del S&P 500 (alto potencial / alto riesgo) ---
    "ARM": {"nombre": "Arm Holdings", "indice": "FUERA", "sector": "Tecnología (R. Unido)"},
    "TSM": {"nombre": "TSMC", "indice": "FUERA", "sector": "Tecnología (Taiwán)"},
    "MSTR": {"nombre": "MicroStrategy", "indice": "FUERA", "sector": "Cripto/Tecnología"},
    "MARA": {"nombre": "Marathon Digital", "indice": "FUERA", "sector": "Cripto"},
    "SHOP": {"nombre": "Shopify", "indice": "FUERA", "sector": "Tecnología (Canadá)"},
    "SNOW": {"nombre": "Snowflake", "indice": "FUERA", "sector": "Tecnología"},
    "GME": {"nombre": "GameStop", "indice": "FUERA", "sector": "Consumo/Meme"},
    "SOFI": {"nombre": "SoFi", "indice": "FUERA", "sector": "Financieras"},
    "RIVN": {"nombre": "Rivian", "indice": "FUERA", "sector": "Autos/Consumo"},
}
TICKERS_STOCKS = list(STOCKS.keys())
STOCKS_SP500 = [t for t, v in STOCKS.items() if v["indice"] == "SP500"]
STOCKS_FUERA = [t for t, v in STOCKS.items() if v["indice"] == "FUERA"]

# ---------------------------------------------------------------------------
# 1c) FECHA DE ENTRADA AL S&P 500 — para NO hacer trampa en el laboratorio
# ---------------------------------------------------------------------------
# Regla de Cardona: "nunca salir del S&P 500". Al probar el método en el pasado,
# una acción SOLO se puede operar DESDE que entró al índice — no antes. Si no,
# cometemos dos trampas: (1) operar algo que no era S&P 500 todavía, y (2) la
# "trampa del superviviente" (probar las ganadoras de HOY en el pasado, sabiendo
# ya cuáles triunfaron -> resultado inflado de mentira).
#
# Fechas APROXIMADAS (compiladas, no de un feed verificado). Las que de verdad
# importan en una ventana de ~10 años son las entradas RECIENTES (marcadas ⚠️);
# las antiguas caen fuera de la ventana y no afectan. Las que están 100% seguras
# hace décadas usan una fecha piso segura.
SP500_DESDE = {
    "AAPL": "1982-11-30", "MSFT": "1994-06-01", "NVDA": "2001-11-30",
    "AMZN": "2005-11-18", "GOOGL": "2006-03-31", "META": "2013-12-23",
    "AVGO": "2014-05-08", "NFLX": "2010-12-20", "MU": "1994-09-27",
    "QCOM": "1999-07-22", "INTC": "1976-01-01", "ADBE": "1997-05-05",
    "CRM": "2008-09-15", "BA": "1957-03-04", "DIS": "1976-01-01",
    "JPM": "1975-01-01", "XOM": "1957-03-04",
    # ⚠️ Entradas recientes — estas SÍ recortan la ventana de prueba:
    "AMD":  "2017-03-20",   # ⚠️
    "TSLA": "2020-12-21",   # ⚠️
    "NOW":  "2019-11-21",   # ⚠️
    "MRVL": "2021-01-01",   # ⚠️ (fecha aprox, verificar)
    "UBER": "2023-12-18",   # ⚠️
    "SMCI": "2024-03-18",   # ⚠️
    "CRWD": "2024-06-24",   # ⚠️
    "PLTR": "2024-09-23",   # ⚠️
    "COIN": "2025-05-19",   # ⚠️
}

# El universo completo (ETFs base + acciones) con nombre, clase, índice y sector.
UNIVERSO = dict(ACTIVOS)
for _t, _v in ACTIVOS.items():
    UNIVERSO[_t] = {**_v, "indice": "ETF", "sector": _v.get("clase", "")}
for _t, _v in STOCKS.items():
    UNIVERSO[_t] = {"nombre": _v["nombre"], "clase": "accion",
                    "indice": _v["indice"], "sector": _v["sector"]}
UNIVERSO_TICKERS = list(UNIVERSO.keys())

# Universos predefinidos para el dashboard:
UNIVERSO_NUCLEO = TICKERS + STOCKS_SP500       # método puro: ETFs + acciones del S&P 500
UNIVERSO_PARALELO = STOCKS_FUERA               # motor paralelo: fuera del S&P 500

# ---------------------------------------------------------------------------
# 2) PROMEDIOS MÓVILES — los niveles dinámicos (Guía, secc. 7)
# ---------------------------------------------------------------------------
# El de 20 y 40 definen la alineación (estrategia MA40); 100 y 200 son los
# pisos/techos "de fondo" con los que suele haber confluencia.
MEDIAS = [20, 40, 100, 200]

# "En una tendencia, el precio toca el promedio móvil y rebota."
# ¿Qué tan cerca del promedio consideramos que el precio lo está "tocando"?
# Expresado como % de distancia del cierre al promedio.
CERCANIA_MEDIA_PCT = 0.6   # ±0.6% se considera "tocando" el promedio

# Caídas (estrategias "caída normal" y "caída fuerte"). Umbral del propio Cardona:
# "caída normal = menos del 1.5% (en SPY ~3-5 USD); caída fuerte = más del 1.5%".
CAIDA_NORMAL_MIN_PCT = 0.4   # una caída "normal" real, no ruido (SPY ~3-5 USD ≈ 0.5%)
CAIDA_NORMAL_MAX_PCT = 1.5   # caída pequeña: hasta 1.5% (ni alcanza el MA40)
CAIDA_FUERTE_MIN_PCT = 1.5   # caída fuerte: más de 1.5% (pasa el MA40, a veces MA100/200)
CAIDA_VENTANA = 15           # velas hacia atrás para medir la caída reciente (pico->valle)

# Gap al alza (estrategia "gap"). Un gap = la apertura salta por encima del máximo
# del día previo (queda un hueco). El "piso del gap" es ese máximo previo: mientras
# el precio lo respete (no lo cierre), la tendencia alcista sigue -> CALL.
GAP_MIN_PCT = 0.5            # salto mínimo (%) sobre el máximo previo para llamarlo gap
GAP_LOOKBACK = 5            # velas recientes donde buscar el gap

# Zona cara (regla de Cardona: "no comprar lejos del promedio, tras una gran subida").
# Si el precio está MÁS de este % por encima del MA40, está caro/extendido: no se
# compran calls ahí (esperar la corrección hacia el promedio). Generoso para no
# estorbar a gaps ni caídas normales, pero corta el "comprar carísimo arriba".
ZONA_CARA_PCT = 8.0

# ---------------------------------------------------------------------------
# 3) PATRONES DE VELA (Compendio, secc. 1.1)
# ---------------------------------------------------------------------------
# "La vela por sí sola no tiene poder; el poder está en la vela + la zona."
# Parámetros geométricos para reconocer cada patrón:
VELA = {
    # Martillo (alcista): cuerpo pequeño arriba, mecha inferior larga.
    "martillo_mecha_inf_min": 2.0,   # mecha inferior >= 2x el cuerpo
    "martillo_mecha_sup_max": 0.5,   # mecha superior <= 0.5x el cuerpo
    # Hanger / martillo invertido (bajista): imagen espejo en zona cara.
    "hanger_mecha_sup_min": 2.0,
    "hanger_mecha_inf_max": 0.5,
    # Vela sólida: cuerpo grande, colas cortas ("sin tantas colas").
    "solida_cuerpo_min": 0.6,        # cuerpo >= 60% del rango total de la vela
}

# ---------------------------------------------------------------------------
# 4) ZONAS: piso / techo (Guía secc. 6-7, Compendio 1.2)
# ---------------------------------------------------------------------------
# Detección de soportes/resistencias históricos por pivotes.
PIVOTE_VENTANA = 3        # nº de velas a cada lado para marcar un pivote (máx/mín local)
SR_TOLERANCIA_PCT = 1.0  # niveles a <1% se agrupan como el mismo soporte/resistencia
SR_MIN_TOQUES = 2        # "une los puntos donde el precio rebotó" -> mín. 2 toques
SR_CERCANIA_PCT = 1.0    # ¿el precio actual está "en" el nivel? a <1%

# ---------------------------------------------------------------------------
# 5) CONFLUENCIA (Guía secc. 7): "cuantas más cosas coincidan, más confiable"
# ---------------------------------------------------------------------------
# Peso de cada ingrediente en el score de confluencia (0-100).
PESOS_CONFLUENCIA = {
    "zona":          25,   # el precio está en zona extrema (piso/techo)
    "media":         20,   # confluencia con un promedio móvil
    "soporte":       20,   # confluencia con soporte/resistencia trazado
    "vela":          15,   # apareció la vela de señal correcta
    "ruptura":       20,   # SE DIO la ruptura de línea (la confirmación real)
}
# Umbral mínimo para que una configuración se muestre como "señal" y no ruido.
UMBRAL_SENAL = 60

# ---------------------------------------------------------------------------
# 6) LA OPCIÓN: strike y vencimiento (Guía secc. 9, Compendio 1.4)
# ---------------------------------------------------------------------------
# "strike ligeramente fuera del dinero (OTM)": call por encima, put por debajo.
# ---------------------------------------------------------------------------
# 6b) LA REGLA REAL DE CARDONA (día 2): el strike se elige por PRECIO DE LA PRIMA
# ---------------------------------------------------------------------------
# "Estos precios son los que primero se duplican. Los primeros strikes en lograr
#  el 100% coincide que tienen estos valores." — A. Cardona (día 2)
# Se busca el contrato FUERA DEL DINERO cuya prima caiga en este rango.
# Mismo rango para CALL y para PUT.
PRIMA_OBJETIVO = {
    "SPY": (0.25, 0.30), "QQQ": (0.25, 0.30),
    "AAPL": (0.45, 0.80), "META": (0.45, 0.80),
    "AMZN": (0.60, 0.80), "NFLX": (0.60, 0.80), "NVDA": (0.60, 0.80),
    "PLTR": (0.60, 0.80), "GLD": (0.60, 0.80), "XOM": (0.60, 0.80),
    "CVX": (0.60, 0.80), "TNA": (0.60, 0.80), "MRNA": (0.50, 0.60),
    "TSLA": (2.50, 3.00),
    "BAC": (0.10, 0.20), "SLV": (0.10, 0.20), "USO": (0.10, 0.20),
}
PRIMA_OBJETIVO_DEFECTO = (0.45, 0.80)   # para los tickers no listados

# Vencimiento POR ESTRATEGIA (días). Cardona día 2: "una semana" como norma,
# pero cada estrategia necesita su tiempo. ⛔ Prohibido el "hoy para hoy" (0DTE).
VENCIMIENTO_POR_ESTRATEGIA = {
    "ma40": 2, "canal": 2, "caida_normal": 2, "caida_fuerte": 2,
    "gap_normal_alza": 2, "gap_bajista_alza": 2, "gap": 2,
    "piso_fuerte": 4, "primer_gap_alza": 4,
    "tres_semanas": 7,
    # puts
    "primera_vela_roja": 3, "ruptura_piso_gap": 3, "modelo_4_pasos": 3,
    "hanger_diario": 5, "techo_fuerte": 4,
}
VENCIMIENTO_MINIMO_DIAS = 1   # nunca 0DTE

# Volumen "alto" por activo — SOLO se usa en la estrategia primer gap al alza.
# "Para las demás yo ni miro el volumen." — A. Cardona
VOLUMEN_ALTO = {
    "SPY": 20_000_000, "QQQ": 20_000_000, "AAPL": 12_000_000,
    "META": 3_000_000, "NFLX": 1_000_000, "TSLA": 15_000_000,
    "GLD": 2_000_000, "MRNA": 2_000_000, "BAC": 10_000_000,
}
VOLUMEN_ALTO_DEFECTO = 3_000_000

STRIKE_OTM_PCT = 1.5       # strike ~1.5% OTM (referencia de respaldo si no hay cadena)
STRIKE_OTM_AGRESIVO = 6.0  # strike ~6% OTM (opción AGRESIVA / lotería: improbable, ×10 posible)
VENCIMIENTO_DIAS_AGRESIVO = 7  # vencimiento corto = más apalancamiento (más gamma)
# "Vencimiento: cortos, máximo ~3 semanas."
VENCIMIENTO_DIAS_MIN = 7   # "una semana es el tiempo mínimo"
VENCIMIENTO_DIAS_MAX = 21  # "tres semanas para que se mueva"

# ---------------------------------------------------------------------------
# 7) SALIDA Y RIESGO (Guía secc. 9-10)
# ---------------------------------------------------------------------------
# Premio mínimo (multiplicador) que debe poder alcanzar la opción SEGÚN el tiempo
# que hay que esperar. Regla de Oscar: mientras más días esperas, más grande el premio.
# Piso absoluto ×1.5 (recuperas capital + 0.5 de ganancia con la regla del +50%).
PREMIO_MINIMO_POR_ESTRATEGIA = {
    "ma40": 2.0,          # intradía -> rápido: mínimo ×2
    "canal": 2.0,         # intradía -> rápido: mínimo ×2
    "caida_normal": 2.0,  # intradía -> rápido: mínimo ×2
    "caida_fuerte": 2.0,  # intradía -> rápido: mínimo ×2
    "gap": 3.0,           # diario -> medio: mínimo ×3
    "piso_fuerte": 3.0,   # 1-4 días -> medio: mínimo ×3
    "tres_semanas": 5.0,  # varios días/semanas -> lento: mínimo ×5
    # nuevas del día 2
    "gap_bajista_alza": 2.0, "primer_gap_alza": 3.0,
    "primera_vela_roja": 2.0, "ruptura_piso_gap": 2.0, "modelo_4_pasos": 2.0,
    "hanger_diario": 3.0, "techo_fuerte": 3.0,
}
PREMIO_PISO_ABSOLUTO = 1.5

# El Vigilante SOLO avisa de las "rápidas": ×2 alcanzable en ~1 día con buena probabilidad.
VIGILANTE_SOLO_RAPIDAS = True
VIGILANTE_MAX_DIAS_X2 = 1.5   # el ×2 debe darse en 1.5 días o menos
VIGILANTE_MIN_PROB_X2 = 40    # con al menos 40% de probabilidad histórica

# Regla de salida (decidida con Oscar 2026-07-15): cuando la opción DOBLA (+100%),
# vender la MITAD. Con eso recuperas TODA tu inversión (la mitad de algo que vale ×2 =
# tu capital completo) y la otra mitad corre 100% gratis buscando el ×3, ×5, ×10.
# Es el punto matemáticamente perfecto para "recuperar y dejar correr".
SALIDA_GANANCIA_PCT = 100      # al +100% (dobló)
SALIDA_VENDER_FRACCION = 0.5   # vender la mitad -> recuperas todo el capital; el resto corre gratis
RIESGO_MAX_CAPITAL_PCT = 10   # "nunca más del 5-10% del capital en opciones"
CAPITAL_PRUEBA = 500          # "apartar ~$500 que podemos perder por completo"

# ---------------------------------------------------------------------------
# 8) LAS 4 ESTRATEGIAS (Guía secc. 8, Compendio parte 2)
# ---------------------------------------------------------------------------
# Cada una es el MISMO motor con distinto marco de tiempo y disparador.
ESTRATEGIAS = {
    "ma40": {
        "nombre": "Promedio móvil de 40",
        "marco": "1h",
        "intervalo": "1h",   # marco de datos con el que se evalúa
        "velocidad": "rápida (mismo día)",
        "vigilancia": "alta",
        "ritmo": "⏱️ Intradía",
        "ritmo_txt": "Vigila durante el día · actúa cuando rompe",
        "descripcion": "20 sobre 40, caída toca el MA40, ruptura de línea bajista con vela verde -> CALL",
    },
    "canal": {
        "nombre": "Canal bajista",
        "marco": "1h/1d",
        "intervalo": "1h",
        "velocidad": "media",
        "vigilancia": "media",
        "ritmo": "⏱️ Intradía",
        "ritmo_txt": "Vigila durante el día · actúa cuando rompe",
        "descripcion": "canal descendente, ruptura de la línea de techo con vela verde -> CALL (espejo: piso con roja -> PUT)",
    },
    "caida_normal": {
        "nombre": "Caída normal",
        "marco": "1h",
        "intervalo": "1h",
        "velocidad": "rápida (mismo día)",
        "vigilancia": "alta",
        "ritmo": "⏱️ Intradía",
        "ritmo_txt": "Vigila durante el día · actúa cuando rompe",
        "descripcion": "caída pequeña (<1.5%) que ni toca el MA40 + ruptura de línea bajista con vela verde -> CALL",
    },
    "caida_fuerte": {
        "nombre": "Caída fuerte",
        "marco": "1h",
        "intervalo": "1h",
        "velocidad": "rápida (mismo día)",
        "vigilancia": "alta",
        "ritmo": "⏱️ Intradía",
        "ritmo_txt": "Vigila durante el día · actúa cuando rompe",
        "descripcion": "caída grande (>1.5%) que pasa el MA40 (a veces MA100/200) + ruptura con vela verde -> CALL",
    },
    # ---- CALLS nuevas (día 2) ----
    "gap_bajista_alza": {
        "nombre": "Gap bajista al alza", "marco": "1h", "intervalo": "1h",
        "velocidad": "rápida (1-2 días)", "vigilancia": "alta",
        "ritmo": "⏱️ Intradía", "ritmo_txt": "Confirma a las 11 · avisa que viene la ruptura",
        "horario": "desde_11",
        "descripcion": "abre ABAJO y las dos primeras velas son verdes -> CALL. Excepción: SÍ se puede dentro de un canal bajista; además anuncia que la ruptura del techo viene cerca",
    },
    "primer_gap_alza": {
        "nombre": "Primer gap al alza", "marco": "1d+1h", "intervalo": "1d",
        "velocidad": "3-4 días", "vigilancia": "baja",
        "ritmo": "🔔 Al cierre", "ritmo_txt": "Se decide 3:58pm · la más exigente (pide volumen)",
        "horario": "cierre",
        "descripcion": "viene de una caída, en zona de piso fuerte, salta arriba, primera vela VERDE, respeta el piso del gap todo el día y hay una vela verde sólida con ALTO VOLUMEN -> CALL (patentada)",
    },
    # ---- PUTS (día 2) ----
    "primera_vela_roja": {
        "nombre": "Primera vela roja de apertura", "marco": "30m", "intervalo": "30m",
        "velocidad": "1-3 días", "vigilancia": "alta",
        "ritmo": "🌅 A las 10:00", "ritmo_txt": "LA ÚNICA que se compra a las 10am",
        "horario": "vela_10",
        "descripcion": "la primera vela del día (9:30-10:00) cierra ROJA -> PUT a las 10:00 en punto. Contexto: canal bajista o zona de techo",
    },
    "ruptura_piso_gap": {
        "nombre": "Ruptura del piso del gap", "marco": "1h", "intervalo": "1h",
        "velocidad": "1-3 días", "vigilancia": "alta",
        "ritmo": "⏱️ Intradía", "ritmo_txt": "Desde las 11 · vela roja final rompe el piso",
        "horario": "desde_11",
        "descripcion": "primera vela verde marca el piso del gap; una vela roja FINAL lo rompe -> PUT. Mejor lejos del MA40 en tendencia alcista, o pegado al techo en canal bajista",
    },
    "modelo_4_pasos": {
        "nombre": "Modelo de los 4 pasos", "marco": "1h", "intervalo": "1h",
        "velocidad": "1-3 días", "vigilancia": "alta",
        "ritmo": "⏱️ Intradía", "ritmo_txt": "Desde las 11 · dentro del canal, en zona cara",
        "horario": "desde_11",
        "descripcion": "dentro de canal bajista + zona cara + una vela roja borra a la verde + rompe la línea de piso -> PUT",
    },
    "hanger_diario": {
        "nombre": "Hanger en diario", "marco": "1d", "intervalo": "1d",
        "velocidad": "4-5 días", "vigilancia": "baja",
        "ritmo": "🔔 Al cierre", "ritmo_txt": "Se decide 3:57pm · el color del hanger da igual",
        "horario": "cierre",
        "descripcion": "vela diaria con cola larga ARRIBA y cuerpo pequeño (hanger, cualquier color) en zona cara -> PUT",
    },
    "techo_fuerte": {
        "nombre": "Techo fuerte", "marco": "1d+1h", "intervalo": "1d",
        "velocidad": "3-5 días", "vigilancia": "media",
        "ritmo": "📅 Diario", "ritmo_txt": "El espejo del piso fuerte · 15-22x",
        "horario": "desde_11",
        "descripcion": "en diario MA200 sobre MA100 y techo tocado varias veces; una vela roja sólida rompe la línea de piso -> PUT",
    },
    "gap": {
        "nombre": "Gap al alza",
        "marco": "1d",
        "intervalo": "1d",
        "velocidad": "1-4 días",
        "vigilancia": "media-baja",
        "ritmo": "📅 Diario",
        "ritmo_txt": "Decides al cierre · el gap suele empujar varios días",
        "descripcion": "la acción abre con un salto (gap) por encima del máximo previo; mientras respete el piso del gap y confirme con vela verde -> CALL",
    },
    "piso_fuerte": {
        "nombre": "Piso fuerte",
        "marco": "1d",
        "intervalo": "1d",
        "velocidad": "1-4 días",
        "vigilancia": "media-baja",
        "ritmo": "📅 Diario",
        "ritmo_txt": "Decides cerca del cierre · dura 1-4 días · poca vigilancia",
        "descripcion": "precio en piso histórico fuerte + señal -> CALL. Recomendada para empezar.",
    },
    "tres_semanas": {
        "nombre": "Tres semanas",
        "marco": "1d/1wk",
        "intervalo": "1d",
        "velocidad": "lenta",
        "vigilancia": "baja",
        "ritmo": "📅 Semanal",
        "ritmo_txt": "Decides al cierre · aguantas semanas · casi sin vigilancia",
        "descripcion": "opción OTM barata con ~3 semanas de plazo, se deja madurar. Recomendada para empezar.",
    },
}
# Estrategias sugeridas para arrancar (las más pausadas).
ESTRATEGIAS_INICIALES = ["piso_fuerte", "tres_semanas"]

# ---------------------------------------------------------------------------
# 9) EL BOT DE PAPEL (Alpaca) — opera solo, con primas reales, sin riesgo real
# ---------------------------------------------------------------------------
# Tamaño pensado como si el capital REAL fuera este, para que las muestras del
# papel se parezcan a lo que Oscar haría de verdad (aunque el paper tenga $100k).
BOT_CAPITAL = 1000            # capital de referencia (para dimensionar como en real)
BOT_RIESGO_POR_TRADE = 250    # objetivo de $ arriesgados por operación (la prima total)
BOT_MAX_PRIMA_1_CONTRATO = 400  # si ni 1 contrato cabe pero cuesta <= esto, compra 1; si no, salta
BOT_MAX_POSICIONES = 4        # cuántas operaciones abiertas a la vez (deja pólvora seca)
BOT_HORA_INICIO = "10:00"     # no abrir nuevas antes de esta hora ET (spreads anchos al abrir)
# Strike: el laboratorio (10 años, 4500 muestras) mostró que comprar MÁS barato/lejos
# (6% OTM) sube el ROI de +2% a +14% — menos aciertos pero colas mucho más gordas (×10
# pasa de 0.2% a 1.6%). Es la asimetría pura. Y de paso caben en el capital chico.
BOT_OTM_PCT = 6.0
# Estrategias del bot. Las diarias están validadas por el laboratorio. Las intradía
# (ma40/canal) NO se pueden validar en el laboratorio (Yahoo no da histórico horario);
# se prueban HACIA ADELANTE en papel = EXPERIMENTO vigilado (y dan actividad diaria).
BOT_ESTRATEGIAS = ["piso_fuerte", "tres_semanas", "ma40", "canal"]
# "Opción barata" = el edge que validó el laboratorio (vol BAJA del activo al entrar).
# Solo entra si la volatilidad anual del activo está por debajo de esto. Q1 puro fue
# <=0.28 (+28%); hasta ~0.38 sigue positivo. 0.35 = balance señal/edge.
BOT_GASOLINA_MAX_VOL = 0.35
# Salida partida: (ganancia, fracción a vender). El resto CORRE (lo que hace ganar).
BOT_SALIDA = [(0.30, 1 / 3), (1.00, 1 / 3)]   # +30% vende 1/3, +100% vende 1/3, corre 1/3
BOT_CORRE_STOP_DESDE_PICO = 0.40   # el pedazo que corre: sale si cae 40% desde su pico
