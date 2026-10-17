"""Gateway HTTP del agente: WhatsApp, chat web (plan B) y webhooks de billetera y Didit."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from collections import defaultdict
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from agente import consentimiento, whatsapp
from agente.config import get_settings
from agente.conversacion import Conversaciones
from agente.herramientas import llamar_interna

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("gateway")

app = FastAPI(title="Agente Caja de Barrio")
_estaticos = Path(__file__).parent / "estaticos"

_conversaciones: Conversaciones | None = None
_candados: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
# Mensajes para usuarios del chat web, que no reciben push: el navegador los consulta.
PENDIENTES: dict[str, list[str]] = defaultdict(list)


def conversaciones() -> Conversaciones:
    global _conversaciones
    if _conversaciones is None:
        _conversaciones = Conversaciones()
    return _conversaciones


def usar_conversaciones(c: Conversaciones) -> None:
    """Permite inyectar otra implementación (pruebas)."""
    global _conversaciones
    _conversaciones = c


def _es_whatsapp(usuario: str) -> bool:
    return usuario.isdigit() and bool(get_settings().whatsapp_token)


async def entregar(usuario: str, textos: list[str]) -> None:
    if _es_whatsapp(usuario):
        for t in textos:
            await whatsapp.enviar_texto(usuario, t)
    else:
        PENDIENTES[usuario].extend(textos)


async def procesar(usuario: str, texto: str) -> list[str]:
    async with _candados[usuario]:
        try:
            return await conversaciones().responder(usuario, texto)
        except Exception:
            log.exception("usuario=%s fallo del agente", usuario)
            return ["Uy, tuve un problema procesando tu mensaje. ¿Me lo repites en un momento?"]


async def procesar_y_entregar(usuario: str, texto: str) -> None:
    await entregar(usuario, await procesar(usuario, texto))


async def avisar(usuario: str, aviso: str) -> None:
    """Le cuenta algo a un usuario en su propia sesión: el agente lo redacta y se lo entrega."""
    await procesar_y_entregar(usuario, f"{consentimiento.PREFIJO_SISTEMA} {aviso}")


consentimiento.NOTIFICADOR = avisar


# ------------------------------------------------------------------- salud

@app.get("/health")
async def health() -> dict:
    return {"ok": True, "modo_herramientas": get_settings().modo_herramientas}


# ---------------------------------------------------------------- WhatsApp

@app.get("/webhook/whatsapp")
async def verificar_webhook(modo: str = Query("", alias="hub.mode"),
                            token: str = Query("", alias="hub.verify_token"),
                            reto: str = Query("", alias="hub.challenge")) -> PlainTextResponse:
    if modo == "subscribe" and token and token == get_settings().whatsapp_verify_token:
        return PlainTextResponse(reto)
    raise HTTPException(403, "Token de verificación inválido")


@app.post("/webhook/whatsapp")
async def recibir_whatsapp(request: Request, tareas: BackgroundTasks) -> dict:
    # Meta exige responder rápido; el agente corre en segundo plano.
    for numero, texto in whatsapp.extraer_mensajes(await request.json()):
        log.info("whatsapp entrante de=%s", numero)
        tareas.add_task(procesar_y_entregar, numero, texto)
    return {"ok": True}


# ------------------------------------------------------------- chat web (plan B)

# --------------------------------------------------- avisos del backend (panel)

class Aviso(BaseModel):
    whatsapp: str
    aviso: str


@app.post("/internal/avisos", status_code=202)
async def recibir_aviso(a: Aviso, request: Request, tareas: BackgroundTasks) -> dict:
    """El backend pide avisarle algo a una persona (por ejemplo, que el panel aprobó su tienda)."""
    token = get_settings().servicio_token
    if not token or not hmac.compare_digest(request.headers.get("X-Servicio-Token", ""), token):
        raise HTTPException(401, "Token de servicio inválido")
    log.info("aviso del backend para whatsapp=*%s", a.whatsapp[-4:])
    tareas.add_task(avisar, a.whatsapp, a.aviso)
    return {"ok": True}


class MensajeChat(BaseModel):
    usuario: str
    mensaje: str


@app.post("/chat")
async def chat(m: MensajeChat) -> dict:
    respuestas = await procesar(m.usuario, m.mensaje)
    return {"respuestas": respuestas + PENDIENTES.pop(m.usuario, [])}


@app.get("/chat/pendientes")
async def chat_pendientes(usuario: str) -> dict:
    return {"respuestas": PENDIENTES.pop(usuario, [])}


@app.get("/", response_class=HTMLResponse)
async def chat_web() -> str:
    return (_estaticos / "chat.html").read_text(encoding="utf-8")


# --------------------------------------------------------------- políticas

@app.get("/politicas", response_class=HTMLResponse)
async def politicas() -> str:
    return (_estaticos / "politicas.html").read_text(encoding="utf-8")


# --------------------------------------------------------- Open Payments: fin del grant

def _pagina(titulo: str, cuerpo: str) -> str:
    return (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            f"<title>{titulo}</title><body style='font-family:system-ui;max-width:28rem;margin:3rem auto;"
            f"padding:0 1rem'><h2>{titulo}</h2>{cuerpo}</body>")


@app.get("/op/finish", response_class=HTMLResponse)
async def op_finish(tareas: BackgroundTasks, grant_id: str, interact_ref: str = "", hash: str = "",
                    result: str = "") -> str:
    if result == "grant_rejected" or not interact_ref:
        return _pagina("Cupo rechazado", "<p>No se aprobó ningún cupo. Puedes volver a WhatsApp.</p>")
    # El backend verifica el hash del callback antes de continuar el grant.
    r = await llamar_interna("continuar_permiso", grant_id=grant_id, interact_ref=interact_ref, hash=hash)
    if "error" in r:
        log.warning("grant_id=%s continuar_permiso falló: %s", grant_id, r["error"])
        return _pagina("No pudimos confirmar", f"<p>{r['error']}</p>")
    log.info("grant_id=%s cupo aprobado persona_id=%s", grant_id, r["persona_id"])
    tareas.add_task(avisar, r["whatsapp"], "La persona aprobó su cupo en la billetera.")
    return _pagina("¡Listo!", "<p>Aprobaste tu cupo. Vuelve a WhatsApp para seguir.</p>")


# ---------------------------------------------------------------- Didit

async def procesar_resultado_didit(cuerpo: str, firma: str) -> dict:
    """Reenvía el webhook de Didit al backend (que valida la firma) y le avisa a la persona."""
    r = await llamar_interna("procesar_webhook_didit", cuerpo=cuerpo, firma=firma)
    if "error" in r:
        log.warning("webhook Didit rechazado: %s", r["error"])
        return r
    if r.get("procesado"):
        aviso = "La verificación de identidad fue APROBADA." if r.get("aprobada", r.get("aprobado")) else             "La verificación de identidad fue RECHAZADA: la cara no coincide."
        await avisar(r["whatsapp"], f"{aviso} (motivo: {r.get('motivo', '')})")
    return r


@app.get("/didit/retorno", response_class=HTMLResponse)
async def didit_retorno(session_id: str, tareas: BackgroundTasks) -> str:
    """A donde vuelve el navegador al terminar Didit. Sirve aunque no llegue el webhook: le pide
    el resultado al backend (que se lo pregunta a Didit) y le avisa a la persona en su chat."""
    r = await llamar_interna("estado_verificacion", session_id=session_id)
    if "error" in r:
        log.warning("session_id=%s retorno de Didit sin estado: %s", session_id, r["error"])
        return _pagina("No pudimos confirmar", "<p>Vuelve al chat y escribe LISTO.</p>")
    if r.get("pendiente"):
        return _pagina("Estamos revisando", "<p>Didit todavía está procesando. Vuelve al chat y escribe LISTO "
                       "en un momento.</p>")
    aviso = "La verificación de identidad fue APROBADA." if r["aprobada"] else         "La verificación de identidad fue RECHAZADA: la cara no coincide."
    tareas.add_task(avisar, r["whatsapp"], f"{aviso} (motivo: {r['motivo']})")
    return _pagina("¡Gracias!", "<p>Ya tenemos el resultado. Vuelve al chat para seguir.</p>")


@app.post("/webhook/didit")
async def webhook_didit(request: Request, tareas: BackgroundTasks) -> dict:
    cuerpo = (await request.body()).decode("utf-8")
    tareas.add_task(procesar_resultado_didit, cuerpo, request.headers.get("X-Signature-V2", ""))
    return {"ok": True}


# ------------------------------------------------- simuladores (solo modo simulado)

def _solo_simulado() -> None:
    if get_settings().modo_herramientas != "simulado":
        raise HTTPException(404)


@app.get("/simulador/billetera", response_class=HTMLResponse)
async def simulador_billetera(grant_id: str, interact_ref: str) -> str:
    _solo_simulado()
    from agente.herramientas import simuladas

    g = simuladas.ALMACEN.grants.get(grant_id)
    if g is None:
        raise HTTPException(404, "Permiso inexistente")
    ok = f"/op/finish?grant_id={grant_id}&interact_ref={interact_ref}"
    no = f"/op/finish?grant_id={grant_id}&result=grant_rejected"
    return _pagina("Billetera de prueba", f"<p>Caja de Barrio pide un cupo para pagar tus retiros: hasta "
                   f"<b>{g['limite']:,} {g['moneda']}</b> cada 7 días. Cada retiro lo apruebas en el chat.</p>"
                   f"<p><a href='{ok}'>Aprobar cupo</a> · <a href='{no}'>Rechazar</a></p>")


@app.get("/simulador/didit", response_class=HTMLResponse)
async def simulador_didit(session_id: str) -> str:
    _solo_simulado()
    return _pagina("Verificación de identidad de prueba",
                   f"<p>Sesión <code>{session_id}</code></p>"
                   f"<p><a href='/simulador/didit/resultado?session_id={session_id}&aprobado=true'>La cara coincide</a>"
                   f" · <a href='/simulador/didit/resultado?session_id={session_id}&aprobado=false'>"
                   f"La cara NO coincide</a></p>")


@app.get("/simulador/didit/resultado", response_class=HTMLResponse)
async def simulador_didit_resultado(session_id: str, aprobado: bool, tareas: BackgroundTasks) -> str:
    _solo_simulado()
    cuerpo = json.dumps({"session_id": session_id, "status": "Approved" if aprobado else "Declined"})
    tareas.add_task(procesar_resultado_didit, cuerpo, "")
    return _pagina("Verificación enviada", "<p>Vuelve a WhatsApp.</p>")
