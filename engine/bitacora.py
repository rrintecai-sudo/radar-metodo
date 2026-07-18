"""
bitacora.py — El registro de operaciones (dos libros: simulación y real).

Esto es lo que convierte el método en algo COMPROBABLE. Sin registro, ni ganando
se aprende. Cada operación se anota con su entrada y su salida, y el motor calcula
lo único que importa al final: la EXPECTATIVA (¿el conjunto da positivo después de
contar las perdedoras?).

Guarda en un archivo JSON. Local: persiste siempre. En la nube: persiste mientras
la instancia esté viva; por eso hay exportar/importar para no perder nada.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ET = timezone(timedelta(hours=-4))
ARCHIVO = Path(__file__).resolve().parent.parent / "data" / "bitacora.json"


def _cargar() -> list[dict]:
    if ARCHIVO.exists():
        try:
            return json.loads(ARCHIVO.read_text())
        except Exception:
            return []
    return []


def _guardar(trades: list[dict]):
    ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVO.write_text(json.dumps(trades, indent=2, ensure_ascii=False))


def _nuevo_id(trades: list[dict]) -> int:
    return (max((t.get("id", 0) for t in trades), default=0) + 1)


def agregar(libro: str, ticker: str, direccion: str, estrategia: str, strike: float,
            prima_entrada: float, contratos: int, nota: str = "",
            vencimiento: str = "") -> dict:
    """
    Registra una nueva operación ABIERTA.
    `vencimiento` (YYYY-MM-DD) es clave: con él el Vigilante puede avisarte
    cuándo se acerca el vencimiento y cuánto vale tu contrato ahora.
    """
    trades = _cargar()
    t = {
        "id": _nuevo_id(trades),
        "libro": libro,                       # "simulacion" | "real"
        "fecha_entrada": datetime.now(ET).isoformat(timespec="minutes"),
        "ticker": ticker.upper(),
        "direccion": direccion,               # "call" | "put"
        "estrategia": estrategia,
        "strike": float(strike),
        "prima_entrada": float(prima_entrada),
        "contratos": int(contratos),
        "vencimiento": vencimiento,           # YYYY-MM-DD (para avisos de salida)
        "nota": nota,
        "estado": "abierta",
        "fecha_salida": None,
        "prima_salida": None,
        "resultado_pct": None,
        "resultado_usd": None,
    }
    trades.append(t)
    _guardar(trades)
    return t


def cerrar(trade_id: int, prima_salida: float):
    """Cierra una operación con la prima de salida y calcula el resultado."""
    trades = _cargar()
    for t in trades:
        if t["id"] == trade_id and t["estado"] == "abierta":
            pe = t["prima_entrada"]
            t["prima_salida"] = float(prima_salida)
            t["resultado_pct"] = (prima_salida - pe) / pe * 100 if pe else 0
            t["resultado_usd"] = (prima_salida - pe) * 100 * t["contratos"]
            t["estado"] = "cerrada"
            t["fecha_salida"] = datetime.now(ET).isoformat(timespec="minutes")
            break
    _guardar(trades)


def eliminar(trade_id: int):
    _guardar([t for t in _cargar() if t["id"] != trade_id])


def listar(libro: str | None = None, estado: str | None = None) -> list[dict]:
    out = _cargar()
    if libro:
        out = [t for t in out if t["libro"] == libro]
    if estado:
        out = [t for t in out if t["estado"] == estado]
    return sorted(out, key=lambda t: t["id"], reverse=True)


def metricas(libro: str) -> dict:
    """
    Las métricas que deciden si el método funciona EN TUS MANOS.
    La estrella: EXPECTATIVA por operación (>0 = el conjunto da positivo).
    """
    cerradas = [t for t in _cargar() if t["libro"] == libro and t["estado"] == "cerrada"]
    n = len(cerradas)
    if n == 0:
        return {"n": 0}
    ganadoras = [t for t in cerradas if t["resultado_pct"] > 0]
    perdedoras = [t for t in cerradas if t["resultado_pct"] <= 0]
    win_rate = len(ganadoras) / n * 100
    avg_win = sum(t["resultado_pct"] for t in ganadoras) / len(ganadoras) if ganadoras else 0
    avg_loss = sum(t["resultado_pct"] for t in perdedoras) / len(perdedoras) if perdedoras else 0
    # expectativa por operación (en %): promedio ponderado de ganar y perder
    expectativa = (win_rate / 100) * avg_win + (1 - win_rate / 100) * avg_loss
    total_usd = sum(t["resultado_usd"] for t in cerradas)
    return {
        "n": n,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "expectativa": expectativa,
        "total_usd": total_usd,
        "ganadoras": len(ganadoras),
        "perdedoras": len(perdedoras),
    }


def exportar_csv(libro: str | None = None) -> str:
    """Devuelve la bitácora como texto CSV (para descargar)."""
    import csv
    import io
    cols = ["id", "libro", "fecha_entrada", "ticker", "direccion", "estrategia", "strike",
            "prima_entrada", "contratos", "estado", "fecha_salida", "prima_salida",
            "resultado_pct", "resultado_usd", "nota"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for t in listar(libro):
        w.writerow(t)
    return buf.getvalue()


def importar_csv(texto: str) -> int:
    """Carga operaciones desde un CSV exportado (reemplaza la bitácora). Devuelve cuántas."""
    import csv
    import io
    filas = list(csv.DictReader(io.StringIO(texto)))
    trades = []
    for r in filas:
        def num(x, tipo=float):
            try:
                return tipo(x)
            except Exception:
                return None
        trades.append({
            "id": num(r.get("id"), int) or _nuevo_id(trades),
            "libro": r.get("libro", "simulacion"),
            "fecha_entrada": r.get("fecha_entrada", ""),
            "ticker": r.get("ticker", ""),
            "direccion": r.get("direccion", "call"),
            "estrategia": r.get("estrategia", ""),
            "strike": num(r.get("strike")) or 0,
            "prima_entrada": num(r.get("prima_entrada")) or 0,
            "contratos": num(r.get("contratos"), int) or 1,
            "nota": r.get("nota", ""),
            "estado": r.get("estado", "abierta"),
            "fecha_salida": r.get("fecha_salida") or None,
            "prima_salida": num(r.get("prima_salida")),
            "resultado_pct": num(r.get("resultado_pct")),
            "resultado_usd": num(r.get("resultado_usd")),
        })
    _guardar(trades)
    return len(trades)
