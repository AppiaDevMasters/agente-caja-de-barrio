"""Herramientas del coordinador que dependen de lo que la persona escribió de verdad.

Aceptar políticas, aprobar un pago y confirmar que se recibió el dinero no pueden quedar
a criterio del modelo: cada herramienta lee el mensaje real de este turno y se niega si
no contiene la palabra esperada o si el turno lo originó un aviso del sistema. Luego
llama la herramienta interna del MCP, que guarda el registro en base.

También vive aquí `avisar_contraparte`, para que el agente le hable a ambas partes.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from typing import Awaitable, Callable, Literal, Optional

from google.adk.tools import ToolContext

from agente.herramientas import llamar_interna

log = logging.getLogger("agente")

PREFIJO_SISTEMA = "[sistema]"

# El gateway registra aquí cómo hacerle llegar un aviso a otro usuario (su propia sesión).
Notificador = Callable[[str, str], Awaitable[None]]
NOTIFICADOR: Optional[Notificador] = None
_tareas: set[asyncio.Task] = set()


def _mensaje_del_turno(tool_context: ToolContext) -> str:
    contenido = tool_context.user_content
    if not contenido or not contenido.parts:
        return ""
    return "".join(p.text or "" for p in contenido.parts).strip()


def _palabras(texto: str) -> set[str]:
    sin_tildes = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    return set(re.findall(r"[a-z]+", sin_tildes))


def _revela_codigo(mensaje: str, codigo: Optional[str]) -> bool:
    """El código de 4 dígitos solo lo conoce el cliente; ningún aviso al tendero puede llevarlo."""
    if codigo and codigo in re.sub(r"\D", " ", mensaje).split():
        return True
    return re.search(r"(?<![\d.,])\d{4}(?![\d.,])", mensaje) is not None


def _rechazo_si_es_sistema(texto: str) -> Optional[dict]:
    if not texto or texto.startswith(PREFIJO_SISTEMA):
        return {"error": "Esto solo lo puede decidir la persona con su propio mensaje; pídeselo."}
    return None


async def aceptar_politicas(tool_context: ToolContext) -> dict:
    """Registra que la persona aceptó las políticas. Úsala SOLO cuando su mensaje dice "acepto"."""
    texto = _mensaje_del_turno(tool_context)
    if rechazo := _rechazo_si_es_sistema(texto):
        return rechazo
    palabras = _palabras(texto)
    if "no" in palabras or not palabras & {"acepto", "aceptar", "aceptamos"}:
        return {"error": "La persona no escribió que acepta. Sin aceptar no puede continuar."}
    return await llamar_interna("aceptar_politicas", whatsapp=tool_context.state["whatsapp"],
                                version=tool_context.state.get("politicas_version", ""), texto_usuario=texto)


async def aprobar_pago(reserva_id: str, tool_context: ToolContext) -> dict:
    """Registra en base que la persona aprobó el pago. Úsala SOLO cuando su mensaje dice "aprobar".

    Args:
        reserva_id: Reserva cuyo pago cotizado se aprueba.
    """
    texto = _mensaje_del_turno(tool_context)
    if rechazo := _rechazo_si_es_sistema(texto):
        return rechazo
    palabras = _palabras(texto)
    if "no" in palabras or not palabras & {"aprobar", "apruebo", "aprobado", "aprueba"}:
        return {"error": "Para aprobar el pago la persona debe escribir APROBAR."}
    persona_id = tool_context.state.get("persona_id")
    if not persona_id:
        return {"error": "No sé quién es la persona; consulta primero su identidad."}
    return await llamar_interna("registrar_aprobacion", reserva_id=reserva_id, persona_id=persona_id,
                                texto_usuario=texto, canal="whatsapp")


async def confirmar_recibido(reserva_id: str, recibido: bool, tool_context: ToolContext) -> dict:
    """La persona que retira confirma (recibido=true) o niega (false) que le entregaron el dinero.

    Args:
        reserva_id: Reserva del retiro.
        recibido: true si dice que sí recibió los billetes; false si dice que no.
    """
    texto = _mensaje_del_turno(tool_context)
    if rechazo := _rechazo_si_es_sistema(texto):
        return rechazo
    return await llamar_interna("confirmar_recibido", reserva_id=reserva_id, recibido=recibido,
                                texto_usuario=texto)


async def avisar_contraparte(reserva_id: str, para: Literal["tendero", "cliente"], mensaje: str,
                             tool_context: ToolContext) -> dict:
    """Le avisa algo a la otra parte del retiro (al tendero o a la persona que retira) por su chat.

    Args:
        reserva_id: Reserva del retiro.
        para: "tendero" o "cliente".
        mensaje: Qué debe saber la otra parte, en una o dos frases.
    """
    if _mensaje_del_turno(tool_context).startswith(PREFIJO_SISTEMA):
        return {"error": "No reenvíes avisos del sistema; solo responde a esta persona."}
    if para == "tendero" and _revela_codigo(mensaje, tool_context.state.get("codigo_retiro")):
        return {"error": "Nunca le des el código de retiro al tendero: él debe pedírselo al cliente en el "
                         "mostrador. Reescribe el aviso sin el código."}
    reserva = await llamar_interna("consultar_reserva", reserva_id=reserva_id)
    if "error" in reserva:
        return reserva
    destino = reserva["whatsapp_tendero"] if para == "tendero" else reserva["whatsapp_cliente"]
    if destino == tool_context.state.get("whatsapp"):
        return {"error": "Esa es la misma persona con la que hablas."}
    if NOTIFICADOR is None:
        return {"error": "No hay canal para avisar a la otra parte."}
    aviso = f"Aviso sobre el retiro {reserva_id} ({reserva['nombre_tienda']}): {mensaje}"
    tarea = asyncio.create_task(NOTIFICADOR(destino, aviso))
    _tareas.add(tarea)
    tarea.add_done_callback(_tareas.discard)
    log.info("reserva_id=%s aviso a %s", reserva_id, para)
    return {"ok": True}
