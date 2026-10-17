"""Conversaciones con el agente, compartidas entre WhatsApp, el chat web y la UI de ADK.

Todas usan el mismo servicio de sesiones y el mismo nombre de app que la UI de ADK, así que
un aviso (del tendero, de Didit, de la billetera o del panel) llega a la conversación que la
persona tiene abierta, venga de donde venga.
"""

from __future__ import annotations

import logging

from google.adk.agents.run_config import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, InMemorySessionService, Session
from google.genai import types

from agente.agentes import crear_agente_raiz

# Mismo nombre que la carpeta de la app en ui/ (lo que la UI de ADK usa como app_name).
APP = "caja_de_barrio"
# Tope de llamadas al modelo del coordinador por mensaje (cada especialista tiene su propio tope).
CONFIG = RunConfig(max_llm_calls=30)
log = logging.getLogger(__name__)


class Conversaciones:
    def __init__(self, runner: Runner | None = None, sesiones: BaseSessionService | None = None) -> None:
        self.sesiones = sesiones or InMemorySessionService()
        self.runner = runner or Runner(app_name=APP, agent=crear_agente_raiz(), session_service=self.sesiones)

    async def _sesion_de(self, usuario: str) -> Session:
        """La conversación más reciente de esa persona; si no tiene, una nueva con su número."""
        existentes = (await self.sesiones.list_sessions(app_name=APP, user_id=usuario)).sessions
        if existentes:
            return max(existentes, key=lambda s: s.last_update_time)
        return await self.sesiones.create_session(app_name=APP, user_id=usuario, session_id=usuario,
                                                  state={"whatsapp": usuario})

    async def responder(self, usuario: str, texto: str) -> list[str]:
        """Pasa el mensaje al coordinador y devuelve los textos que debe recibir la persona."""
        sesion = await self._sesion_de(usuario)
        mensaje = types.Content(role="user", parts=[types.Part.from_text(text=texto)])
        respuestas: list[str] = []
        async for evento in self.runner.run_async(user_id=usuario, session_id=sesion.id, new_message=mensaje,
                                                  run_config=CONFIG):
            if evento.author != "coordinador" or not evento.content or not evento.content.parts:
                continue
            texto_evento = "".join(p.text for p in evento.content.parts if p.text and not p.thought)
            if texto_evento.strip():
                respuestas.append(texto_evento.strip())
        log.info("usuario=%s sesion=%s respuestas=%d", usuario, sesion.id, len(respuestas))
        return respuestas
