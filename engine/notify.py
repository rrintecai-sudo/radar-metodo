"""
notify.py — Manda las alertas (para no estar pegado a la pantalla).

Dos canales:
  - macOS: notificación en tu Mac (funciona sin configurar nada).
  - Telegram: mensaje a tu celular (requiere crear un bot una sola vez).

La config de Telegram vive en `alertas.json` (ver alertas.example.json):
    {"telegram_token": "123:ABC...", "telegram_chat_id": "12345678"}
"""
from __future__ import annotations

import json
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

CONF = Path(__file__).resolve().parent.parent / "alertas.json"


def _conf() -> dict:
    if CONF.exists():
        try:
            return json.loads(CONF.read_text())
        except Exception:
            return {}
    return {}


RADAR_URL = "http://localhost:8502"


def sonido() -> bool:
    """Sonido garantizado (no depende de permisos de notificación)."""
    try:
        subprocess.Popen(["afplay", "/System/Library/Sounds/Glass.aiff"])
        return True
    except Exception:
        return False


def popup(titulo: str, texto: str, url: str = RADAR_URL) -> bool:
    """
    Ventana emergente que SALTA AL FRENTE de todo e interrumpe lo que estés
    haciendo (la mejor forma de no perderse una entrada si estás concentrado).
    Tiene un botón 'Abrir Radar' que abre el tablero en el navegador.
    """
    ti = titulo.replace("\\", "").replace('"', "'")
    tx = texto.replace("\\", "").replace('"', "'").replace("\n", '" & linefeed & "')
    script = f'''
    tell application "System Events"
        activate
        set r to display dialog "{tx}" with title "{ti}" buttons {{"Después", "Abrir Radar"}} default button "Abrir Radar" with icon caution giving up after 3600
    end tell
    if button returned of r is "Abrir Radar" then
        do shell script "open {url}"
    end if
    '''
    try:
        subprocess.Popen(["osascript", "-e", script])  # no bloquea; espera tu clic
        return True
    except Exception:
        return False


def mac(titulo: str, texto: str) -> bool:
    """Aviso en macOS: ventana emergente que interrumpe + sonido garantizado."""
    s = sonido()
    p = popup(titulo, texto)
    return s or p


def telegram(texto: str) -> bool:
    """Manda un mensaje a tu Telegram (si está configurado el bot)."""
    c = _conf()
    token, chat = c.get("telegram_token"), c.get("telegram_chat_id")
    if not token or not chat:
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat, "text": texto, "parse_mode": "Markdown"}).encode()
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=12)
        return True
    except Exception as e:
        print(f"[notify] Telegram falló: {e}")
        return False


def enviar(titulo: str, texto: str) -> dict:
    """Manda por todos los canales disponibles. Devuelve qué funcionó."""
    return {"mac": mac(titulo, texto), "telegram": telegram(f"*{titulo}*\n{texto}")}


def telegram_configurado() -> bool:
    c = _conf()
    return bool(c.get("telegram_token") and c.get("telegram_chat_id"))
