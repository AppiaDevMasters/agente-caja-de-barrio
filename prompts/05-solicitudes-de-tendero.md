# 05 · Guías para el equipo y registro de tenderos

Herramienta: Claude Code (Claude Opus 5.5). Fecha: 2026-10-16.

## Prompts (textuales)

> bien, va bien hay reglas de oro: (...)

> hay alguna librería de whatsapp, para utilizar si por ejemplo twilio demora o no podemos verificar en tiempo record el tema de whatsapp business?

> hazme un .md detallado de que hacer con esto y subelo a contexto
>
> y ya basado en como cambiamos la arquitectura, el panel lo que hará es revisar solicitudes si alguien quiere acceder como tendero y revisa si la persona verificó sus datos y demas, y puede aprobar o desaprobar, tambien hace revisión de las transacciones y hay una trazabilidad, es decir haz 2 .md para contexto de lo que debe hacer el front que es el panel y como se conecta con el back para eso y el agente y lo que debe hacer quien se está encargando de la parte de whatsapp

> revisa de nuevo el front que tiene nuevos cambios y basado en eso necesito rehagas el documento para front

> Sí, implementa en el agente y los MCP el registro de tenderos por WhatsApp y el endpoint /internal/avisos, con el backend simulado actualizado y commits atómicos sin subir.

## Resultado

- En `contexto-caja-de-barrio`: `guia-whatsapp-meta.md`, `panel-de-control-v2.md` (rehecho sobre el mock del front) y
  la sección 13 del contrato.
- Agente: flujo de solicitante (políticas, datos, pin, billetera, Didit `alta_tendero`), avisos del panel en
  `POST /internal/avisos` con token de servicio.
- Lógica de referencia y backend simulado con solicitudes, checks, `/admin` mínimo y página `/dev/solicitudes`.
- Probado de punta a punta con Gemini: solicitud → revisión → aprobación → aviso → el nuevo tendero publica su efectivo.
