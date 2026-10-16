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
    "identidad": {"identidad": ["consultar_persona", "verificar_cedula", "crear_sesion_facial", "estado_verificacion"]},
    "ubicacion": {
        "mapa": ["buscar_cajas_cercanas", "detalle_tienda", "publicar_efectivo"],
        "caja": ["reservar_efectivo", "cancelar_reserva"],
    },
    "riesgo": {"caja": ["evaluar_riesgo"]},
    "pagos": {
        "pagos": ["resolver_wallet", "crear_cobro", "cotizar", "pedir_permiso", "pagar", "estado_cobro"],
        "caja": ["consultar_reserva", "confirmar_entrega"],
    },
}

# Herramientas que solo llama el gateway (webhooks); nunca se exponen al modelo.
INTERNAS = {"continuar_permiso": "pagos", "marcar_face_match": "caja"}


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
    """Llama una herramienta interna (continuar_permiso, marcar_face_match)."""
    if nombre not in INTERNAS:
        raise ValueError(f"{nombre} no es una herramienta interna")
    if get_settings().modo_herramientas == "simulado":
        return getattr(simuladas, nombre)(**argumentos)

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(_url_servidor(INTERNAS[nombre])) as (leer, escribir, _):
        async with ClientSession(leer, escribir) as sesion:
            await sesion.initialize()
            resultado = await sesion.call_tool(nombre, argumentos)
    if resultado.structuredContent:
        return dict(resultado.structuredContent)
    texto = "".join(getattr(c, "text", "") for c in resultado.content)
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        return {"error" if resultado.isError else "resultado": texto}
