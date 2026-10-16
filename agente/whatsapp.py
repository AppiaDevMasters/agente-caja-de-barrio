"""Cliente mínimo de WhatsApp Cloud API: leer mensajes entrantes y enviar texto."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from agente.config import get_settings

log = logging.getLogger(__name__)


def extraer_mensajes(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """Convierte el webhook de Meta en pares (número, texto para el agente)."""
    mensajes: list[tuple[str, str]] = []
    for entrada in payload.get("entry", []):
        for cambio in entrada.get("changes", []):
            for m in cambio.get("value", {}).get("messages", []):
                numero, tipo = m.get("from"), m.get("type")
                if tipo == "text":
                    texto = m["text"]["body"]
                elif tipo == "location":
                    loc = m["location"]
                    texto = f"[ubicación] lat={loc['latitude']}, lon={loc['longitude']}"
                elif tipo == "interactive":
                    i = m["interactive"]
                    texto = (i.get("button_reply") or i.get("list_reply") or {}).get("title", "")
                elif tipo == "button":
                    texto = m["button"]["text"]
                else:
                    texto = f"[mensaje de tipo {tipo} no soportado]"
                if numero and texto:
                    mensajes.append((numero, texto))
    return mensajes


async def enviar_texto(numero: str, texto: str) -> None:
    s = get_settings()
    url = f"https://graph.facebook.com/{s.whatsapp_api_version}/{s.whatsapp_phone_number_id}/messages"
    cuerpo = {"messaging_product": "whatsapp", "to": numero, "type": "text",
              "text": {"body": texto, "preview_url": True}}
    async with httpx.AsyncClient(timeout=15) as cliente:
        r = await cliente.post(url, json=cuerpo, headers={"Authorization": f"Bearer {s.whatsapp_token}"})
    if r.status_code >= 400:
        log.error("WhatsApp respondió %s: %s", r.status_code, r.text)
