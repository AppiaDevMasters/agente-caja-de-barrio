# 01 · Esqueleto del agente

Herramienta: Claude Code (Claude Opus 5.5). Fecha: 2026-10-16.
Contexto entregado: `contexto-caja-de-barrio/CONTEXTO-AGENTE-caja-de-barrio.md`.

## Prompts (textuales)

> hola claude, quiero que revises todos los repos que hay aquí:
>
> https://github.com/orgs/AppiaDevMasters/repositories
>
> bajate todos los repos y sobre todo utiliza el de contexto para que te llenes de contexto, yo voy a trabajar en el agente y los mcps otro trabajará en el panel y otro en el backend, entonces la idea sería que comencemos con el agente y vamos haciendo pruebas.

> C:\Users\Usuario\hackathonRutaN en esta carpeta guardas todos los repos

> Sí, arranca con el esqueleto del agente usando herramientas simuladas, y ve dejando el AI_USAGE.md y la carpeta prompts/.

> utilizaremos la version 2.5 de adk, la ultima.

> pero no te pongas como co-author

> solo mi cuenta debe aparecer

> y hablame en español

## Resultado

Proyecto `uv` con `google-adk[mcp]==2.5.0`, herramientas simuladas con las mismas firmas que los
MCP, coordinador con cuatro especialistas como `AgentTool`, gateway FastAPI con WhatsApp, chat web,
`/op/finish` y webhook de Didit, y 18 pruebas.
