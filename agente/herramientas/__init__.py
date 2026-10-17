"""Herramientas de cada sub-agente (mínimo privilegio) e invocación de las internas.

En modo "simulado" se usan las funciones de `simuladas.py` como herramientas de
ADK. En modo "mcp" cada sub-agente recibe un McpToolset por servidor con
`tool_filter`, de modo que solo ve sus herramientas y nunca las internas.
"""

from __future__ import annotations

import json
from typing import Any

from agente.config import get_settings
from agente.herramientas import simuladas

# Qué herramientas ve cada agente, agrupadas por servidor MCP.
PERMISOS: dict[str, dict[str, list[str]]] = {
    "coordinador": {"caja": ["consultar_reserva"]},
    "identidad": {"identidad": ["consultar_persona", "verificar_cedula", "registrar_persona",
                                "crear_sesion_facial", "estado_verificacion", "solicitar_ser_tendero",
                                "consultar_solicitud_tendero", "corregir_solicitud_tendero"]},
    "ubicacion": {
        "mapa": ["buscar_cajas_cercanas", "detalle_tienda", "publicar_efectivo"],
        "caja": ["reservar_efectivo", "cancelar_reserva", "reservas_de_tienda"],
    },
    "riesgo": {"caja": ["evaluar_riesgo"]},
    "pagos": {
        "pagos": ["resolver_wallet", "pedir_cupo", "crear_cobro", "cotizar", "pagar", "estado_cobro",
                  "consultar_saldo"],
        "caja": ["consultar_reserva", "confirmar_entrega"],
    },
}

# Herramientas que nunca se exponen al modelo. Las llaman el gateway (webhooks) o las
# herramientas de consentimiento del agente, que antes verifican el mensaje real de la persona.
INTERNAS = {
    "continuar_permiso": "pagos",
    "registrar_aprobacion": "pagos",
    "procesar_webhook_didit": "identidad",
    "aceptar_politicas": "identidad",
    "confirmar_recibido": "caja",
}
# Lecturas que el código también necesita (por ejemplo, para avisarle a la contraparte).
LECTURAS_DESDE_CODIGO = {"consultar_reserva": "caja"}
_LLAMABLES_DESDE_CODIGO = {**INTERNAS, **LECTURAS_DESDE_CODIGO}


def normalizar_respuesta(respuesta: Any) -> Any:
    """Convierte un CallToolResult de MCP (ya volcado a dict) en el JSON plano de la herramienta.

    Así el agente ve lo mismo en modo "mcp" que en modo "simulado".
    """
    if not isinstance(respuesta, dict) or "content" not in respuesta or "isError" not in respuesta:
        return respuesta
    estructurado = respuesta.get("structuredContent")
    if isinstance(estructurado, dict):
        datos = estructurado.get("result", estructurado) if len(estructurado) == 1 else estructurado
    else:
        texto = "".join(c.get("text", "") for c in respuesta.get("content", []) if isinstance(c, dict))
        try:
            datos = json.loads(texto)
        except json.JSONDecodeError:
            datos = {"resultado": texto}
    if respuesta.get("isError") and not (isinstance(datos, dict) and "error" in datos):
        return {"error": datos.get("resultado") if isinstance(datos, dict) else str(datos)}
    return datos


def _url_servidor(servidor: str) -> str:
    s = get_settings()
    return {"pagos": s.mcp_pagos_url, "mapa": s.mcp_mapa_url,
            "caja": s.mcp_caja_url, "identidad": s.mcp_identidad_url}[servidor]


def herramientas_de(agente: str) -> list[Any]:
    permisos = PERMISOS[agente]
    if get_settings().modo_herramientas == "simulado":
        return [getattr(simuladas, nombre) for nombres in permisos.values() for nombre in nombres]

    from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams

    return [
        McpToolset(connection_params=StreamableHTTPConnectionParams(url=_url_servidor(servidor)),
                   tool_filter=nombres)
        for servidor, nombres in permisos.items()
    ]


async def llamar_interna(nombre: str, **argumentos: Any) -> dict:
    """Llama una herramienta interna desde código, nunca desde el modelo."""
    if nombre not in _LLAMABLES_DESDE_CODIGO:
        raise ValueError(f"{nombre} no es una herramienta interna")
    if get_settings().modo_herramientas == "simulado":
        return getattr(simuladas, nombre)(**argumentos)

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(_url_servidor(_LLAMABLES_DESDE_CODIGO[nombre])) as (leer, escribir, _):
        async with ClientSession(leer, escribir) as sesion:
            await sesion.initialize()
            resultado = await sesion.call_tool(nombre, argumentos)
    return normalizar_respuesta(resultado.model_dump(exclude_none=True, mode="json"))
