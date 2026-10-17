"""Un solo proceso con la UI de ADK y el gateway, sobre el mismo servicio de sesiones.

    uvicorn agente.servidor:app --host 0.0.0.0 --port 8080

- /dev-ui/?app=caja_de_barrio&userId=<número>  UI de ADK: cada persona entra con su número.
- /webhook/whatsapp, /webhook/didit, /op/finish, /internal/avisos, /politicas, /chat  El gateway de siempre.

Como las dos partes comparten las sesiones, el aviso al tendero, el resultado de Didit, la vuelta de
la billetera y las decisiones del panel aparecen en la conversación que cada uno tiene abierta en la
UI de ADK (hay que recargar la sesión para verlos: la UI no se refresca sola).
"""

from __future__ import annotations

from pathlib import Path

from fastapi.responses import HTMLResponse
from google.adk.cli import fast_api
from google.adk.sessions import BaseSessionService, InMemorySessionService

from agente import gateway
from agente.config import get_settings
from agente.conversacion import Conversaciones

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


def _servicio_de_sesiones() -> BaseSessionService:
    url = get_settings().sesiones_url
    if not url:
        return InMemorySessionService()
    from google.adk.sessions import DatabaseSessionService

    return DatabaseSessionService(db_url=url)


sesiones = _servicio_de_sesiones()

# La UI de ADK arma su propio servicio de sesiones; se le entrega el mismo objeto para que la UI
# y el gateway vean exactamente las mismas conversaciones.
fast_api.create_session_service_from_options = lambda **_: sesiones

app = fast_api.get_fast_api_app(agents_dir=str(UI_DIR), web=True, use_local_storage=False)
gateway.usar_conversaciones(Conversaciones(sesiones=sesiones))

# Las rutas del gateway van al principio: la UI de ADK monta sus archivos estáticos con un
# Mount al final que se tragaría cualquier ruta agregada después. "/", "/health" y la
# documentación ya los tiene ADK.
_YA_EN_ADK = {"/", "/health", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
for _ruta in reversed([r for r in gateway.app.routes if getattr(r, "path", None) not in _YA_EN_ADK]):
    app.router.routes.insert(0, _ruta)


async def _chat_web() -> str:
    """El chat de dos paneles (plan B); "/" lo usa la UI de ADK para redirigir a /dev-ui."""
    return await gateway.chat_web()


app.router.add_api_route("/chat-web", _chat_web, methods=["GET"], response_class=HTMLResponse)
app.router.routes.insert(0, app.router.routes.pop())
