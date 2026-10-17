# 06 · Despliegue en un VPS y dominio cajadebarrio.lat

Herramienta: Claude Code (Claude Opus 5.5). Fecha: 2026-10-16 y madrugada del 17.

## Prompts (textuales)

> vamos a subir el backend a render, para que el back no tenga que encender tunnel y lo tengamos disponible siempre, haz un pull del back y comencemos a subirlo

Respuestas del equipo a las preguntas del agente:

> ¿Quién maneja la cuenta de Render? — Yo en el dashboard (Recomendado)
>
> ¿Qué subimos a Render? — busquemos un vps que sea gratis o barato, un stack para dejar todo lo del backend listo

> cual es el stack que vamos a utilizar para desplegar el back?

> Sí, sube los 4 commits de deploy/ a main del backend.

> cual sería el costo? porque la idea es qaue sea gratis

> hoy cobrarían? y si utilizamos un stack de render? cual sería o no se podría?

> entonces voy a crear mejor el hetzer, dime donde

> ahora si, que creo aquí?

> esto

(Los dos mensajes anteriores y los siguientes llevaban capturas de la consola de Hetzner: el proyecto y la creación
del servidor.)

> Sí, sube el commit del arreglo de Caddy a main del backend.

> ahora tambien, haz los commits atomicos del agente y demas y subelo

> bien,  vamos a conectar el dominio cajadebarrio.lat y con eso ya para que los endpoint queden bien fijos y demás y sube lo últimos cambios

> ya los puse todos

> haz luego un .md con como el front se va a conectar a esos endpoint, y ahora si comencemos a hacer pruebas y conecta tambien a los agentes y mcp las urls actuales

## Resultado

- Todo el stack en un VPS Hetzner (ARM) con Docker Compose y Caddy (Let's Encrypt): Rafiki, el backend Go, PostGIS,
  el agente y los cuatro MCP.
- Dominio `cajadebarrio.lat`: `op.`, `auth.`, `backend.`, `agente.` y `admin.`.
- En este repo: `deploy/compose.vps.yml` y `deploy/instalar.sh`. El agente y los MCP se unen a la red de Rafiki y las
  sesiones viven en SQLite en un volumen.
- Las URLs de los MCP y del backend apuntan a `https://backend.cajadebarrio.lat/internal`. La UI de ADK queda en
  `agente.cajadebarrio.lat`, con clave, y solo las rutas de retorno son públicas.
- En `contexto-caja-de-barrio`: `conexion-panel-backend.md`.
