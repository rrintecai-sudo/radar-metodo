# 🚂 Desplegar en Railway (privado con contraseña)

## Paso 1 — Iniciar sesión (esto lo haces TÚ, abre el navegador)
En la Terminal, dentro de la carpeta del proyecto:
```bash
railway login
```
Se abre el navegador → confirmas con tu cuenta → listo. Vuelve a la Terminal.

## Paso 2 — Crear el proyecto y desplegar
```bash
railway init --name radar-metodo    # crea el proyecto
railway up                          # sube y despliega (tarda unos minutos)
```

## Paso 3 — Poner tu contraseña privada
Elige TU contraseña (cámbiala por la que quieras) y córrela:
```bash
railway variables --set "RADAR_PASSWORD=tu-contraseña-secreta"
```
Con esto, el dashboard pedirá esa contraseña para entrar. Solo tú (o quien le des la clave) puede acceder.

## Paso 4 — Generar el link público (con candado)
```bash
railway domain
```
Te da una dirección tipo `https://radar-metodo-production.up.railway.app`.
Ábrela → te pedirá la contraseña → entras. ¡Y desde el celular también!

## Notas importantes
- **El Vigilante y las alertas de Mac NO corren en la nube** (son de tu compu). El **dashboard sí** funciona completo. Para alertas desde la nube, se hace aparte más adelante.
- **Tu token de Telegram (`alertas.json`) NO se subió** — está protegido en `.gitignore`.
- Cada vez que cambies el código: `railway up` de nuevo para actualizar.
