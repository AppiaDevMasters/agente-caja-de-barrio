"""Una sesión de ADK por usuario (número de WhatsApp o id del chat web)."""

from __future__ import annotations

import logging

from google.adk.agents.run_config import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agente.agentes import crear_agente_raiz

APP = "caja-de-barrio"
# Tope de llamadas al modelo del coordinador por mensaje (cada especialista tiene su propio tope).
CONFIG = RunConfig(max_llm_calls=30)
log = logging.getLogger(__name__)


class Conversaciones:
    def __init__(self, runner: Runner | None = None) -> None:
        self.sesiones = InMemorySessionService()
        self.runner = runner or Runner(app_name=APP, agent=crear_agente_raiz(), session_service=self.sesiones)

    async def _asegurar_sesion(self, usuario: str) -> None:
        if await self.sesiones.get_session(app_name=APP, user_id=usuario, session_id=usuario) is None:
            await self.sesiones.create_session(app_name=APP, user_id=usuario, session_id=usuario,
                                               state={"whatsapp": usuario})

    async def responder(self, usuario: str, texto: str) -> list[str]:
        """Pasa el mensaje al coordinador y devuelve los textos que debe recibir la persona."""
        await self._asegurar_sesion(usuario)
        mensaje = types.Content(role="user", parts=[types.Part.from_text(text=texto)])
        respuestas: list[str] = []
        async for evento in self.runner.run_async(user_id=usuario, session_id=usuario, new_message=mensaje,
                                                 run_config=CONFIG):
            if evento.author != "coordinador" or not evento.content or not evento.content.parts:
                continue
            texto_evento = "".join(p.text for p in evento.content.parts if p.text and not p.thought)
            if texto_evento.strip():
                respuestas.append(texto_evento.strip())
        log.info("usuario=%s respuestas=%d", usuario, len(respuestas))
        return respuestas
