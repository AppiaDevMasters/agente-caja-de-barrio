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

Abre <http://localhost:8088>: es el chat web (plan B) con **dos paneles**, cliente y tendero, que se
comporta como WhatsApp. El botón 📍 envía la ubicación de Ruta N. En modo simulado, los links de la
billetera (cupo) y de Didit abren páginas de prueba que disparan los mismos webhooks reales.

| Número simulado | Quién |
| --- | --- |
| `573000000001` | Laura (cliente, billetera COP) |
| `573000000002` | Rosa (cliente, paga con la billetera USD de Andrés) |
| `573000000010` | Don Jaime, Tienda Don Jaime (tendero) |
| `573000000011`–`14` | Tenderos de las otras tiendas semilla |
| cualquier otro | Persona no registrada |

## Reglas de oro

1. El agente habla con ambas partes (cliente y tendero).
2. Toda operación empieza con la verificación de identidad en Didit.
3. La entrega se confirma por ambas partes.
4. Comisión del tendero auto-calculada por liquidez + 1% fijo para Caja de Barrio.
5. Políticas obligatorias; el pago se aprueba escribiendo APROBAR en el chat contra un cupo aprobado una vez en la billetera.

Detalle de lo que cambia en la base y el panel: [docs/cambios-para-backend-y-panel.md](docs/cambios-para-backend-y-panel.md).

## Endpoints

| Endpoint | Para qué |
| --- | --- |
| `GET/POST /webhook/whatsapp` | Verificación y mensajes entrantes de Meta (texto, ubicación, botones) |
| `POST /chat`, `GET /chat/pendientes`, `GET /` | Chat web (plan B) |
| `GET /op/finish` | Vuelta del grant interactivo (cupo) de Open Payments → `continuar_permiso` |
| `GET /politicas` | Políticas que la persona debe aceptar |
| `POST /webhook/didit` | Resultado de Didit (firma `X-Signature-V2`) → `marcar_face_match` |
| `GET /health` | Salud del contenedor |

## Pruebas

```bash
uv run pytest
```

Hay una prueba por cada invariante de seguridad, más el gateway y el mínimo privilegio de los agentes.
No llaman al modelo.
