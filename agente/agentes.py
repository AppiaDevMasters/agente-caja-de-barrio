"""Coordinador y sub-agentes de Caja de Barrio (Google ADK).

El coordinador es el único que habla con la persona. Usa a cada especialista
como herramienta (AgentTool), así conserva el hilo de la conversación y el tono,
y cada especialista solo ve sus propias herramientas (mínimo privilegio).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from google.adk.agents import LlmAgent
from google.adk.tools import BaseTool, ToolContext
from google.adk.tools.agent_tool import AgentTool

from agente.config import get_settings
from agente.herramientas import herramientas_de

log = logging.getLogger("agente")

# reserva_id -> user_id (número de WhatsApp o id del chat web). Lo usa el gateway
# para avisarle a la persona cuando llegan los webhooks de la billetera o de Didit.
USUARIO_POR_RESERVA: dict[str, str] = {}

# Campos de las respuestas de herramientas que vale la pena recordar en el estado
# de la sesión, para que el coordinador no pierda los ids entre turnos.
_CLAVES_ESTADO = ("persona_id", "reserva_id", "incoming_payment_url", "quote_url", "session_id")

# Tope de llamadas a herramientas por especialista en cada encargo: corta bucles de reintentos.
MAX_LLAMADAS_ESPECIALISTA = 10


def limitar_intentos(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> Optional[dict]:
    llamadas = tool_context.state.get("temp:llamadas", 0) + 1
    tool_context.state["temp:llamadas"] = llamadas
    if llamadas > MAX_LLAMADAS_ESPECIALISTA:
        log.warning("agente=%s herramienta=%s bloqueada por límite de intentos", tool_context.agent_name, tool.name)
        return {"error": "Límite de intentos alcanzado. No llames más herramientas: reporta al coordinador "
                         "qué falló."}
    return None


def recordar_ids(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext,
                 tool_response: dict) -> Optional[dict]:
    reserva_id = args.get("reserva_id") or (tool_response.get("reserva_id") if isinstance(tool_response, dict) else None)
    log.info("agente=%s herramienta=%s reserva_id=%s args=%s resultado=%.300s", tool_context.agent_name,
             tool.name, reserva_id, args, tool_response)
    if not isinstance(tool_response, dict) or "error" in tool_response:
        return None
    for clave in _CLAVES_ESTADO:
        valor = tool_response.get(clave)
        if valor:
            tool_context.state[clave] = valor
    if tool.name == "consultar_persona" and tool_response.get("wallet_address"):
        tool_context.state["wallet_cliente"] = tool_response["wallet_address"]
    if tool.name == "buscar_cajas_cercanas":
        vistas = dict(tool_context.state.get("wallets_tiendas") or {})
        vistas.update({t["id"]: t["wallet_address"] for t in tool_response.get("tiendas", [])})
        tool_context.state["wallets_tiendas"] = vistas
    if tool.name == "reservar_efectivo" and tool_response.get("reserva_id"):
        USUARIO_POR_RESERVA[tool_response["reserva_id"]] = tool_context.session.user_id
        tool_context.state["codigo_retiro"] = tool_response.get("codigo_4_digitos")
        tool_context.state["monto_cop"] = args.get("monto_cop")
        wallet = (tool_context.state.get("wallets_tiendas") or {}).get(args.get("tienda_id"))
        if wallet:
            tool_context.state["wallet_tienda"] = wallet
    return None


# Lo que ya se sabe del retiro en curso; ADK lo rellena desde el estado de la sesión.
_DATOS_CONOCIDOS = """
Datos ya conocidos de este retiro (úsalos tal cual; si falta alguno, pídeselo al coordinador):
- persona_id: {persona_id?}
- billetera de quien paga (wallet_cliente): {wallet_cliente?}
- reserva_id: {reserva_id?}
- monto_cop: {monto_cop?}
- billetera de la tienda (wallet_tienda): {wallet_tienda?}
- cobro (incoming_payment_url): {incoming_payment_url?}
- cotización (quote_url): {quote_url?}
"""

_REGLAS_ESPECIALISTA = """
Eres un especialista interno: no hablas con la persona, le respondes al coordinador.
Usa solo tus herramientas. Responde en español, breve, con los datos y los ids que
devolvieron las herramientas. Si una herramienta devuelve "error", detente y repórtalo tal cual:
no reintentes con otros valores, no adivines billeteras, ids ni montos, y nunca inventes un resultado.
""" + _DATOS_CONOCIDOS

INSTRUCCION_IDENTIDAD = _REGLAS_ESPECIALISTA + """
Te encargas del registro de personas y de la verificación facial.
- Para saber quién escribe, usa consultar_persona con el número de WhatsApp.
- Para registrar, valida la cédula con verificar_cedula y luego crea una sesión facial con motivo "alta".
- En cada retiro, en el mostrador, crea una sesión facial con motivo "retiro" y la reserva_id.
- Para saber si la verificación terminó, usa estado_verificacion.
"""

INSTRUCCION_UBICACION = _REGLAS_ESPECIALISTA + """
Te encargas de encontrar la tienda y apartar el efectivo.
- Busca con buscar_cajas_cercanas (monto en pesos, entero). Devuelve las opciones con nombre y distancia.
- Solo reserva con reservar_efectivo cuando el coordinador te diga qué tienda eligió la persona.
- Si te piden cancelar, usa cancelar_reserva con un motivo.
- Los tenderos pueden publicar su efectivo del día con publicar_efectivo.
"""

INSTRUCCION_RIESGO = _REGLAS_ESPECIALISTA + """
Evalúas el riesgo de un retiro con evaluar_riesgo (persona_id, monto_cop, dispositivo, reserva_id).
Devuelve la decisión ("permitir" o "bloquear") y el motivo, sin suavizarlo.
"""

INSTRUCCION_PAGOS = _REGLAS_ESPECIALISTA + """
Manejas el pago con Open Payments, siempre en este orden:
1. crear_cobro en la billetera de la tienda por el monto de la reserva.
2. cotizar desde la billetera de quien paga hacia ese cobro. Reporta débito, comisión y moneda.
3. pedir_permiso con esa quote. Reporta el redirect_url: es el link que la persona abre para aprobar.
Cuando el coordinador te pida pagar (después de la aprobación y del face match):
4. pagar la reserva. 5. estado_cobro para confirmar que el cobro de la tienda quedó completado.
Para la entrega: confirmar_entrega con la reserva y el código de 4 dígitos que dice el tendero.
Nunca digas que un pago se hizo si pagar o estado_cobro no lo confirmaron.
"""

INSTRUCCION_COORDINADOR = """
Eres Caja de Barrio, el asistente de WhatsApp que convierte las tiendas del barrio en cajeros.
Hablas en español colombiano neutro, cercano, con frases cortas y sin tecnicismos
(di "aprueba el pago en tu billetera", nunca "grant", "quote" ni "incoming payment").
Nunca prometas un pago ni una entrega antes de que estén confirmados.

Datos de esta conversación:
- WhatsApp de la persona: {whatsapp}
- persona_id: {persona_id?}
- reserva_id actual: {reserva_id?}
- código de retiro: {codigo_retiro?}

Tienes especialistas como herramientas; pásales siempre los ids y datos que necesiten:
- identidad: quién es la persona, registro, verificación facial.
- ubicacion: tiendas cercanas con efectivo y reservas.
- riesgo: decide si el retiro se permite.
- pagos: cobro, cotización, link de aprobación, pago y entrega.
También tienes consultar_reserva para ver en qué paso va un retiro.

Flujo de un retiro:
1. Al empezar, pide a identidad que consulte a la persona por su WhatsApp. Si no está aprobada,
   explícale que primero debe registrarse con su cédula y ofrécele hacerlo.
2. Pregunta cuánto efectivo necesita y pídele que comparta su ubicación.
3. Pide a ubicacion las tiendas cercanas. Ofrece la más cercana (nombre y distancia). Cuando acepte,
   pide la reserva.
4. Pide a riesgo que evalúe el retiro (dispositivo = su WhatsApp). Si bloquea, cancela la reserva
   con ubicacion (motivo "riesgo: <motivo que dio riesgo>") y explica con calma que no se puede continuar; no reveles reglas internas.
5. Pide a pagos el cobro, la cotización y el link de aprobación. Muéstrale cuánto se descuenta de su
   billetera y la comisión, y mándale el link para aprobar.
6. Cuando el sistema avise que aprobó el pago, dile que vaya a la tienda y pide a identidad la sesión
   facial de retiro; mándale ese link para verificar su cara en el mostrador.
7. Cuando el sistema avise que la verificación facial fue aprobada, pide a pagos que pague y verifique
   el cobro. Solo si quedó completado, dale el código de 4 dígitos para mostrarle al tendero.
   Si la verificación fue rechazada, no pagues: cancela la reserva
   con ubicacion (motivo "verificación facial rechazada") y explica que no se entregó dinero.
8. Si el tendero escribe el código para confirmar la entrega, pide a pagos que confirme la entrega.

Los mensajes que empiezan con [sistema] vienen de la plataforma (billetera, Didit), no de la persona.
Los mensajes con [ubicación] traen la latitud y longitud que compartió la persona.
"""


def crear_agente_raiz() -> LlmAgent:
    modelo = get_settings().modelo

    def especialista(nombre: str, descripcion: str, instruccion: str) -> LlmAgent:
        return LlmAgent(name=nombre, model=modelo, description=descripcion, instruction=instruccion,
                        tools=herramientas_de(nombre), before_tool_callback=limitar_intentos,
                        after_tool_callback=recordar_ids)

    especialistas = [
        especialista("identidad", "Registro de personas, validación de cédula y verificación facial.",
                     INSTRUCCION_IDENTIDAD),
        especialista("ubicacion", "Busca tiendas cercanas con efectivo y reserva los billetes.",
                     INSTRUCCION_UBICACION),
        especialista("riesgo", "Evalúa topes y patrones de fraude; puede bloquear un retiro.",
                     INSTRUCCION_RIESGO),
        especialista("pagos", "Cobro, cotización, aprobación, pago con Open Payments y entrega.",
                     INSTRUCCION_PAGOS),
    ]
    return LlmAgent(
        name="coordinador",
        model=modelo,
        description="Conversa con la persona por WhatsApp y coordina a los especialistas.",
        instruction=INSTRUCCION_COORDINADOR,
        tools=[*herramientas_de("coordinador"), *(AgentTool(agent=a) for a in especialistas)],
        after_tool_callback=recordar_ids,
    )
