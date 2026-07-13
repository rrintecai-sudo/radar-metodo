# 🔔 Alertas — que el motor te avise (sin estar pegado a la pantalla)

Tienes dos formas de que el **Vigilante** te avise cuando aparece una entrada:

## 1. Notificaciones en tu Mac (sin configurar nada)

Solo abre **`Iniciar Vigilante.command`** (doble clic). Se queda corriendo y, cuando
detecta una ENTRADA, te salta una notificación en tu Mac (con sonido). Deja esa
ventana abierta durante el día; ciérrala cuando quieras parar.

## 2. Alertas a tu celular por Telegram (recomendado)

Para que te lleguen al teléfono, aunque no estés en la compu. Es una sola vez:

**Paso 1 — Crea tu bot (2 min):**
1. En Telegram, busca **@BotFather** y ábrelo.
2. Escribe `/newbot` y sigue las instrucciones (le pones un nombre).
3. Te dará un **token** parecido a `123456789:ABCdef...`. Cópialo.

**Paso 2 — Consigue tu chat_id:**
1. Búsca tu bot recién creado (por el nombre que le pusiste) y **escríbele "hola"**.
2. En tu navegador abre: `https://api.telegram.org/bot<TU_TOKEN>/getUpdates`
   (reemplaza `<TU_TOKEN>` por tu token).
3. Busca `"chat":{"id":XXXXXXXX` — ese número es tu **chat_id**.

**Paso 3 — Guarda la config:**
1. Copia el archivo `alertas.example.json` y renómbralo a **`alertas.json`**.
2. Pega tu token y tu chat_id:
   ```json
   { "telegram_token": "123456789:ABCdef...", "telegram_chat_id": "12345678" }
   ```
3. Listo. La próxima vez que corra el Vigilante, te llegará al celular.

**Probar que funciona:**
```bash
.venv/bin/python vigilante.py --ahora
```
Si hay alguna entrada, te llega el mensaje. (Si no hay entradas, no manda nada — es normal.)

---

### ¿Cada cuánto vigila?
Por defecto cada **10 minutos**, solo en horario de mercado (pre-market y sesión).
Puedes cambiarlo: `python vigilante.py --cada 5` (cada 5 min).

### ¿No repite alertas?
No. Cada señal se avisa **una sola vez por día**. Al día siguiente, borrón y cuenta nueva.
