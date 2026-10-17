# Uso de IA en este repositorio

| Herramienta | Para qué | Archivos |
| --- | --- | --- |
| Claude Code (Claude Opus 5.5) | Generó el esqueleto del agente a partir del documento de contexto del equipo: configuración, herramientas simuladas con las invariantes de seguridad, coordinador y sub-agentes de ADK, gateway FastAPI, chat web de pruebas, pruebas, Dockerfile y documentación; luego implementó las reglas de oro definidas por el equipo (políticas, Didit primero, comisiones por liquidez, aprobación en chat, doble confirmación) y redactó el borrador de políticas; después adaptó el agente al modo MCP (normalización de respuestas, webhooks reenviados al backend) y escribió el backend simulado que cumple el contrato del backend. El equipo revisó y dirigió cada paso. | `agente/**`, `dev/**`, `tests/**`, `docs/**`, `docker-compose.dev.yml`, `Dockerfile`, `docker-compose.yml`, `.env.example`, `README.md`, `pyproject.toml` |
| Claude Code (Claude Opus 5.5), 16 y 17 de octubre | Desplegó el agente y los MCP en el VPS del equipo con el dominio `cajadebarrio.lat` (`deploy/`), conectó la UI de ADK a las sesiones compartidas y a los avisos del backend, implementó Didit sin webhook (LISTO en el chat y la página `/didit/retorno`) con su backend simulado y sus pruebas, y acompañó la prueba de punta a punta en producción leyendo los logs. El equipo definió la prueba, hizo los registros y la verificación facial, y aprobó cada paso. | `agente/**`, `dev/**`, `tests/**`, `deploy/**`, `ui/**`, `estaticos/**`, `.gitattributes` |
| Gemini (vía Google ADK) | Modelo que ejecuta el agente en tiempo de ejecución. No generó código. | — |

Los prompts reales usados durante el desarrollo están en [`prompts/`](prompts/), en orden.
