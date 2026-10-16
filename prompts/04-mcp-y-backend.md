# 04 · Arquitectura con backend dueño de pagos y MCP delgados

Herramienta: Claude Code (Claude Opus 5.5). Fecha: 2026-10-16.

## Prompts (textuales)

> bien, recuerda que lo importante de  este proyecto será que ahora si los pagos se den, estamos esperando el backend

> entonces ya aquí te doy las llaves verdad? no es el backend que hace eso del pago entonces?
>
> el back lo estan haciendo con node
>
> el mcp de pagos debe conectarse al back verdad?

> perdon, el back lo están haciendo con GO

> mejor dejemos que el backend sea quien maneje los pagos, y nos conectamos a un endpoint del backend
>
> el mcp de pagos que sea quien consuma un endpoint del backend para hacer el pago

> dame un .md para que el backend lo haga y nos lo mande, entonces ya estaríamos preparado con eso

> sube a contexto ese .md para el backend

> comienza a armar todos los mcp
> y si, arma el contrato y subelo a contexto para que el back lo haga

Respuestas a las preguntas de diseño que hizo Claude:

> Datos MCP: Endpoints del backend (Recomendado)
>
> Identidad: El backend

## Resultado

- Contrato completo del backend en `contexto-caja-de-barrio/contrato-backend.md`.
- Cuatro MCP delgados (repos `mcp-*-caja-de-barrio`).
- `dev/backend_simulado.py` y `docker-compose.dev.yml` para probar la cadena completa.
- El agente normaliza las respuestas MCP (llegan como texto JSON dentro de `content`) y reenvía los webhooks
  de Didit y de la billetera al backend.
- Un retiro completo por la cadena usó 18 endpoints del contrato.
