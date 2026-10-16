# Uso de IA en este repositorio

| Herramienta | Para qué | Archivos |
| --- | --- | --- |
| Claude Code (Claude Opus 5.5) | Generó el esqueleto del agente a partir del documento de contexto del equipo: configuración, herramientas simuladas con las invariantes de seguridad, coordinador y sub-agentes de ADK, gateway FastAPI, chat web de pruebas, pruebas, Dockerfile y documentación; luego implementó las reglas de oro definidas por el equipo (políticas, Didit primero, comisiones por liquidez, aprobación en chat, doble confirmación) y redactó el borrador de políticas; después adaptó el agente al modo MCP (normalización de respuestas, webhooks reenviados al backend) y escribió el backend simulado que cumple el contrato del backend. El equipo revisó y dirigió cada paso. | `agente/**`, `dev/**`, `tests/**`, `docs/**`, `docker-compose.dev.yml`, `Dockerfile`, `docker-compose.yml`, `.env.example`, `README.md`, `pyproject.toml` |
| Gemini (vía Google ADK) | Modelo que ejecuta el agente en tiempo de ejecución. No generó código. | — |

Los prompts reales usados durante el desarrollo están en [`prompts/`](prompts/), en orden.
