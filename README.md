# agente-caja-de-barrio

Agente conversacional de **Caja de Barrio** (Open Payments Hackathon Medellín 2026 · AppiaDevMaster).
Gateway FastAPI + coordinador de Google ADK (2.5.0) con cuatro especialistas: identidad, ubicación,
riesgo y pagos. Cada especialista solo ve sus herramientas; las internas (`continuar_permiso`,
`marcar_face_match`) solo las llama el gateway desde los webhooks.

## Modos de herramientas

| `MODO_HERRAMIENTAS` | Qué usa |
| --- | --- |
| `simulado` (por defecto) | Herramientas en memoria en `agente/herramientas/simuladas.py`, con las mismas firmas que los MCP y las invariantes de seguridad validadas en código. Incluye 5 tiendas semilla en Aranjuez y a Laura (`573000000001`) y Rosa (`573000000002`). |
| `mcp` | `McpToolset` por streamable HTTP contra `mcp-pagos`, `mcp-mapa`, `mcp-caja` y `mcp-identidad`, con `tool_filter` por especialista. |

## Correr local

```bash
uv sync
cp .env.example .env   # poner GOOGLE_API_KEY
uv run uvicorn agente.gateway:app --port 8080 --reload
```

Con Docker (queda en el puerto 8088 porque el 8080 suele estar ocupado; se cambia con `AGENTE_PUERTO`):

```bash
docker compose up -d --build
```

Abre <http://localhost:8088> (o el puerto de uvicorn si lo corres sin Docker): es el chat web (plan B) que se comporta como WhatsApp. El botón
📍 envía la ubicación de Ruta N. En modo simulado, los links de aprobación de pago y de
verificación facial abren páginas de prueba (`/simulador/billetera`, `/simulador/didit`) que disparan
los mismos webhooks que la billetera real y Didit.

## Endpoints

| Endpoint | Para qué |
| --- | --- |
| `GET/POST /webhook/whatsapp` | Verificación y mensajes entrantes de Meta (texto, ubicación, botones) |
| `POST /chat`, `GET /chat/pendientes`, `GET /` | Chat web (plan B) |
| `GET /op/finish` | Vuelta del grant interactivo de Open Payments → `continuar_permiso` |
| `POST /webhook/didit` | Resultado de Didit (firma `X-Signature-V2`) → `marcar_face_match` |
| `GET /health` | Salud del contenedor |

## Pruebas

```bash
uv run pytest
```

Hay una prueba por cada invariante de seguridad, más el gateway y el mínimo privilegio de los agentes.
No llaman al modelo.
