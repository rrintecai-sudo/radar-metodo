# Radar del Método 📈

Herramienta digital que ejecuta el **método de opciones de Alejandro Cardona** de forma
automática sobre los 5 activos base (SPY, QQQ, GLD, SLV, USO).

El motor vigila los activos, evalúa el checklist completo del método (zona extrema +
confluencias + vela de señal + ruptura confirmada), le pone un **score de confluencia**
a cada configuración y te muestra las que valen la pena — con la opción sugerida
(strike OTM + vencimiento) y una explicación en español de por qué disparó.

> Educativo. No es asesoría financiera. Las opciones son de alto riesgo.
> Simula (paper money) y mide tu propio registro antes de arriesgar capital real.

## Cómo abrirlo

**Opción fácil:** doble clic en **`Iniciar Radar.command`**. Se abre solo en el navegador.

**Desde la terminal:**
```bash
.venv/bin/streamlit run app.py     # el dashboard web
.venv/bin/python scan.py           # versión rápida por consola (recomendadas)
.venv/bin/python scan.py --todas   # incluye MA40 y canal (datos horarios)
```

## Estados de una señal
- 🟢 **ENTRADA** — se cumplen las dos condiciones juntas (zona + ruptura confirmada).
- 🟡 **VIGILAR** — está en zona y armándose, pero falta la confirmación. Aún NO es entrada.
- ⚪ **NADA** — no cumple; esperar.

## Estructura del proyecto
| Archivo | Qué hace |
|---|---|
| `config.py` | **Todos los parámetros del método** en un solo lugar (fácil de afinar). |
| `engine/data.py` | Baja y cachea precios de los 5 ETFs (Yahoo/yfinance). |
| `engine/indicators.py` | Promedios móviles y patrones de vela (martillo, hanger, sólida). |
| `engine/zones.py` | Zonas, soportes/resistencias, canales y la ruptura de línea. |
| `engine/method.py` | **El motor**: combina todo en señales con score de confluencia. |
| `engine/options.py` | Sugiere strike OTM + vencimiento. |
| `app.py` | El dashboard web. |
| `scan.py` | El Radar por consola. |

## Las 4 estrategias
Todas son el mismo motor con distinto marco de tiempo y disparador:
1. **Promedio móvil de 40** (1h) — rápida, alta vigilancia.
2. **Canal bajista** (1h/1d) — media.
3. **Piso fuerte** (1d) — 1-4 días. *Recomendada para empezar.*
4. **Tres semanas** (1d/1wk) — lenta, baja vigilancia. *Recomendada para empezar.*

## Próximos pasos (pendientes)
- Bitácora automática con dos libros (simulación / real) y cálculo de expectativa.
- Backtester para medir el edge sobre históricos antes de arriesgar.
- Alertas (Telegram/correo) cuando aparece una ENTRADA o toca vender (+50%).
- Cruce con calendario económico (catalizador ✅ / evento peligroso ⚠️).
