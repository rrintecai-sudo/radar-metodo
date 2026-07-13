"""
scan.py — Corre el Radar por consola. Útil para probar el motor sin el dashboard.

Uso:
    python scan.py            # escanea diario (piso fuerte + tres semanas)
    python scan.py --todas    # incluye MA40 y canal (baja datos horarios)
"""
import sys

from config import ESTRATEGIAS_INICIALES, ESTRATEGIAS
from engine import data, method


def main():
    todas = "--todas" in sys.argv

    ests = list(ESTRATEGIAS) if todas else ESTRATEGIAS_INICIALES
    print(f"Escaneando {'las 4 estrategias' if todas else 'piso fuerte + tres semanas'} en su marco de tiempo...")
    señales = method.escanear_completo(estrategias=ests)

    print("\n" + "=" * 70)
    print("  RADAR DEL MÉTODO — señales de hoy")
    print("=" * 70)
    iconos = {"ENTRADA": "🟢", "VIGILAR": "🟡", "NADA": "⚪"}
    for s in señales:
        if s["estado"] == "NADA":
            continue
        print(f"\n{iconos[s['estado']]} {s['estado']}  {s['ticker']}  ·  {s['estrategia_nombre']} ({s['marco']})")
        print(f"   Dirección: {s['direccion'].upper()}   Precio: {s['precio']:.2f}   Score confluencia: {s['score']}/100")
        print(f"   Opción: {s['opcion']['nota']}")
        for c in s["cumplidos"]:
            print(f"     ✓ {c}")
        if s["faltan"]:
            print(f"     falta: {', '.join(s['faltan'])}")

    activas = [s for s in señales if s["estado"] != "NADA"]
    if not activas:
        print("\n  Sin señales activas hoy. El método dice: esperar. (Es lo normal la mayoría de los días.)")
    print("\n" + "=" * 70)
    print(f"  Evaluadas {len(señales)} combinaciones activo×estrategia. {len(activas)} en vigilancia/entrada.")
    print("=" * 70)


if __name__ == "__main__":
    main()
