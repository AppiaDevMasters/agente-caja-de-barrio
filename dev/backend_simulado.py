"""Backend simulado que cumple contexto-caja-de-barrio/contrato-backend.md.

Sirve para probar la cadena completa agente → MCP → backend mientras el backend en Go no está.
Toda la lógica de negocio es la de `agente/herramientas/simuladas.py` (implementación de referencia);
aquí solo se traduce a los endpoints HTTP del contrato.

Simula Didit y la billetera como lo harían de verdad: Didit le manda el webhook al gateway del
agente y la billetera redirige a OP_FINISH_URL; el agente los reenvía a este backend por los MCP.

    uvicorn dev.backend_simulado:app --port 8190
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable

import httpx
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from agente.herramientas import simuladas as s

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("backend-simulado")

SERVICIO_TOKEN = os.getenv("SERVICIO_TOKEN", "")
OP_FINISH_URL = os.getenv("OP_FINISH_URL", "http://localhost:8088/op/finish")
DIDIT_CALLBACK_URL = os.getenv("DIDIT_CALLBACK_URL", "http://agente:8080/webhook/didit")
AGENTE_URL = os.getenv("AGENTE_URL", "http://agente:8080")

app = FastAPI(title="Backend simulado de Caja de Barrio")


class ErrorContrato(Exception):
    def __init__(self, status: int, codigo: str, mensaje: str):
        self.status, self.codigo, self.mensaje = status, codigo, mensaje


@app.exception_handler(ErrorContrato)
async def _error_contrato(_: Request, e: ErrorContrato) -> JSONResponse:
    return JSONResponse(status_code=e.status, content={"error": {"codigo": e.codigo, "mensaje": e.mensaje}})


@app.middleware("http")
async def _token(request: Request, call_next):
    if request.url.path.startswith("/internal") and SERVICIO_TOKEN and \
            request.headers.get("X-Servicio-Token") != SERVICIO_TOKEN:
        return JSONResponse(status_code=401, content={"error": {"codigo": "NO_AUTORIZADO",
                                                                "mensaje": "Token de servicio inválido."}})
    return await call_next(request)


def _codigo(mensaje: str) -> tuple[int, str]:
    m = mensaje.lower()
    if "no existe" in m or "inexistente" in m or "no se encontró" in m:
        return 404, "NO_ENCONTRADO"
    for clave, codigo in [("políticas", "SIN_POLITICAS"), ("didit", "SIN_VERIFICACION"),
                          ("verificación facial", "SIN_FACE_MATCH"), ("riesgo", "SIN_RIESGO"),
                          ("aprobar", "SIN_APROBACION"), ("supera el cupo", "CUPO_EXCEDIDO"),
                          ("cupo", "SIN_CUPO"), ("cotización venció", "COTIZACION_VENCIDA"),
                          ("código no coincide", "CODIGO_INCORRECTO"), ("solo entrega hasta", "TOPE_EXCEDIDO"),
                          ("no coinciden", "DATOS_NO_COINCIDEN"), ("estado", "ESTADO_INVALIDO")]:
        if clave in m:
            return 409, codigo
    return 409, "RECHAZADO"


def _ok(funcion: Callable[..., dict], **kwargs: Any) -> dict:
    r = funcion(**kwargs)
    if "error" in r:
        status, codigo = _codigo(r["error"])
        raise ErrorContrato(status, codigo, r["error"])
    return r


# ------------------------------------------------------------------ salud

@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.post("/dev/reiniciar")
async def reiniciar() -> dict:
    s.reiniciar()
    return {"ok": True}


# --------------------------------------------------------------- identidad

@app.get("/internal/identidad/personas")
async def consultar_persona(whatsapp: str) -> dict:
    return s.consultar_persona(whatsapp)


@app.post("/internal/identidad/politicas/aceptaciones", status_code=201)
async def aceptar_politicas(datos: dict) -> dict:
    return _ok(s.aceptar_politicas, **datos)


@app.post("/internal/identidad/cedulas/verificar")
async def verificar_cedula(datos: dict) -> dict:
    return _ok(s.verificar_cedula, **datos)


@app.post("/internal/identidad/personas", status_code=201)
async def registrar_persona(datos: dict) -> dict:
    return _ok(s.registrar_persona, **datos)


@app.post("/internal/identidad/verificaciones", status_code=201)
async def crear_sesion_facial(datos: dict) -> dict:
    return _ok(s.crear_sesion_facial, **datos)


@app.get("/internal/identidad/verificaciones/{session_id}")
async def estado_verificacion(session_id: str) -> dict:
    return _ok(s.estado_verificacion, session_id=session_id)


@app.post("/internal/identidad/webhooks/didit")
async def webhook_didit(datos: dict) -> dict:
    # El Didit real firma con X-Signature-V2; el simulado no firma.
    return _ok(s.procesar_webhook_didit, cuerpo=datos["cuerpo"], firma=datos.get("firma", ""))


@app.post("/internal/identidad/solicitudes-tendero", status_code=201)
async def solicitar_ser_tendero(datos: dict) -> dict:
    return _ok(s.solicitar_ser_tendero, **datos)


@app.get("/internal/identidad/solicitudes-tendero")
async def consultar_solicitud_tendero(whatsapp: str) -> dict:
    return s.consultar_solicitud_tendero(whatsapp)


@app.put("/internal/identidad/solicitudes-tendero/{solicitud_id}")
async def corregir_solicitud_tendero(solicitud_id: str, datos: dict) -> dict:
    return _ok(s.corregir_solicitud_tendero, solicitud_id=solicitud_id, **datos)


# ------------------------------------------- panel: /admin mínimo para solicitudes
# El backend de Go implementa la API /admin completa (panel-de-control-v2.md). Aquí solo
# lo necesario para probar el ciclo de una solicitud de tendero de punta a punta.

async def avisar_al_agente(whatsapp: str, aviso: str) -> None:
    async with httpx.AsyncClient(timeout=180) as cliente:
        r = await cliente.post(f"{AGENTE_URL}/internal/avisos", json={"whatsapp": whatsapp, "aviso": aviso},
                               headers={"X-Servicio-Token": SERVICIO_TOKEN})
    log.info("aviso al agente para %s -> %s", whatsapp[-4:], r.status_code)


@app.get("/admin/solicitudes-tendero")
async def listar_solicitudes(estado: str = "") -> dict:
    return s.listar_solicitudes(estado)


@app.get("/admin/solicitudes-tendero/{solicitud_id}")
async def detalle_solicitud(solicitud_id: str) -> dict:
    return _ok(s.detalle_solicitud, solicitud_id=solicitud_id)


@app.post("/admin/solicitudes-tendero/{solicitud_id}/{accion}")
async def decidir_solicitud(solicitud_id: str, accion: str, datos: dict, tareas: BackgroundTasks) -> dict:
    decision = {"aprobar": "aprobar", "rechazar": "rechazar", "pedir-correccion": "pedir_correccion"}.get(accion)
    if decision is None:
        raise HTTPException(404)
    r = _ok(s.decidir_solicitud, solicitud_id=solicitud_id, decision=decision, motivo=datos.get("motivo", ""),
            nivel=datos.get("nivel", "basico"), campos=datos.get("campos"))
    tareas.add_task(avisar_al_agente, r["whatsapp"], r["aviso"])
    return r


@app.post("/admin/tenderos", status_code=201)
async def registrar_tendero(datos: dict, tareas: BackgroundTasks) -> dict:
    r = _ok(s.registrar_tendero_panel, **datos)
    tareas.add_task(avisar_al_agente, r["whatsapp"], r["aviso"])
    return r


@app.get("/admin/saldos")
async def saldos() -> dict:
    items = [{"wallet_address": w, "saldo": v, "moneda": s.WALLETS[w][0]} for w, v in s.ALMACEN.saldos.items()]
    return {"items": items, "total": len(items)}


@app.get("/dev/tenderos", response_class=HTMLResponse)
async def pagina_tenderos() -> str:
    """Formulario mínimo de "Registrar tendero" mientras el panel no está conectado."""
    filas = "".join(
        f"<tr><td>{t.id}</td><td>{t.nombre}</td><td>{t.whatsapp_tendero}</td><td>{t.estado}</td>"
        f"<td>{s.ALMACEN.saldos.get(t.wallet_address, 0):,.0f}</td></tr>" for t in s.ALMACEN.tiendas.values())
    formulario = (
        "<form method=post action='/dev/tenderos'>"
        "<p><input name=nombre_tienda placeholder='Nombre de la tienda' required></p>"
        "<p><input name=direccion placeholder='Dirección' required></p>"
        "<p><input name=lat value='6.2770' size=8> <input name=lon value='-75.5570' size=8></p>"
        "<p><select name=nivel><option>basico</option><option selected>comercio</option></select></p>"
        "<p><input name=whatsapp_tendero placeholder='WhatsApp (5730...)' required></p>"
        "<p><input name=nombre_tendero placeholder='Nombre del tendero' required></p>"
        "<p><button>Registrar tendero</button></p></form>")
    return _pagina("Registrar tendero (dev)", formulario +
                   "<table border=1 cellpadding=6 style='border-collapse:collapse;font-size:14px'>"
                   "<tr><th>Id</th><th>Tienda</th><th>WhatsApp</th><th>Estado</th><th>Saldo</th></tr>"
                   f"{filas}</table>")


@app.post("/dev/tenderos", response_class=HTMLResponse)
async def registrar_desde_pagina(request: Request, tareas: BackgroundTasks) -> str:
    form = dict(await request.form())
    datos = {**form, "lat": float(form["lat"]), "lon": float(form["lon"]),
             "motivo": "Alta de tendero desde la página de desarrollo."}
    try:
        r = await registrar_tendero(datos, tareas)
        cuerpo = f"<p>Tienda {r['tienda_id']} creada ({r['estado']}). El agente le avisa al tendero.</p>"
    except ErrorContrato as e:
        cuerpo = f"<p>{e.mensaje}</p>"
    return _pagina("Tendero registrado", cuerpo + "<p><a href='/dev/tenderos'>Volver</a></p>")


@app.get("/dev/solicitudes", response_class=HTMLResponse)
async def pagina_solicitudes() -> str:
    """Página mínima para decidir solicitudes mientras el panel no está conectado."""
    filas = []
    for x in s.listar_solicitudes()["items"]:
        checks = " ".join(f"{c['clave']}:{c['estado']}" for c in x["checks"])
        acciones = ""
        if x["estado"] == "en_revision":
            acciones = "".join(
                f"<form method=post action='/dev/solicitudes/{x['id']}/{a}' style='display:inline'>"
                f"<button>{t}</button></form> "
                for a, t in [("aprobar", "Aprobar (básico)"), ("pedir-correccion", "Pedir corregir ubicación"),
                             ("rechazar", "Rechazar")])
        filas.append(f"<tr><td>{x['id']}</td><td>{x['tienda']['nombre']}</td><td>{x['estado']}</td>"
                     f"<td><small>{checks}</small></td><td>{acciones}</td></tr>")
    tabla = "".join(filas) or "<tr><td colspan=5>Sin solicitudes</td></tr>"
    return _pagina("Solicitudes de tendero (dev)",
                   "<table border=1 cellpadding=6 style='border-collapse:collapse;font-size:14px'>"
                   "<tr><th>Id</th><th>Tienda</th><th>Estado</th><th>Checks</th><th>Acción</th></tr>"
                   f"{tabla}</table><p><a href='/dev/solicitudes'>Recargar</a></p>")


@app.post("/dev/solicitudes/{solicitud_id}/{accion}", response_class=HTMLResponse)
async def decidir_desde_pagina(solicitud_id: str, accion: str, tareas: BackgroundTasks) -> str:
    datos = {"motivo": "Revisión manual desde la página de desarrollo.", "nivel": "basico",
             "campos": ["ubicacion"] if accion == "pedir-correccion" else None}
    try:
        await decidir_solicitud(solicitud_id, accion, datos, tareas)
        cuerpo = "<p>Listo. El agente le avisa a la persona por su chat.</p>"
    except ErrorContrato as e:
        cuerpo = f"<p>{e.mensaje}</p>"
    return _pagina("Decisión registrada", cuerpo + "<p><a href='/dev/solicitudes'>Volver</a></p>")


# -------------------------------------------------------------------- mapa

@app.get("/internal/mapa/tiendas/cercanas")
async def tiendas_cercanas(lat: float, lon: float, monto_cop: int, radio_m: int = 1500) -> dict:
    return s.buscar_cajas_cercanas(lat, lon, monto_cop, radio_m)


@app.get("/internal/mapa/tiendas/{tienda_id}")
async def detalle_tienda(tienda_id: str) -> dict:
    return _ok(s.detalle_tienda, tienda_id=tienda_id)


@app.put("/internal/mapa/tiendas/{tienda_id}/efectivo")
async def publicar_efectivo(tienda_id: str, datos: dict) -> dict:
    return _ok(s.publicar_efectivo, tienda_id=tienda_id, **datos)


# -------------------------------------------------------------------- caja

@app.post("/internal/caja/reservas", status_code=201)
async def reservar(datos: dict) -> dict:
    return _ok(s.reservar_efectivo, **datos)


@app.get("/internal/caja/reservas/{reserva_id}")
async def consultar_reserva(reserva_id: str) -> dict:
    return _ok(s.consultar_reserva, reserva_id=reserva_id)


@app.get("/internal/caja/tiendas/{tienda_id}/reservas")
async def reservas_de_tienda(tienda_id: str) -> dict:
    return _ok(s.reservas_de_tienda, tienda_id=tienda_id)


@app.post("/internal/caja/reservas/{reserva_id}/cancelar")
async def cancelar(reserva_id: str, datos: dict) -> dict:
    return _ok(s.cancelar_reserva, reserva_id=reserva_id, **datos)


@app.post("/internal/caja/reservas/{reserva_id}/riesgo")
async def riesgo(reserva_id: str, datos: dict) -> dict:
    return _ok(s.evaluar_riesgo, reserva_id=reserva_id, **datos)


@app.post("/internal/caja/reservas/{reserva_id}/entrega-tendero")
async def entrega_tendero(reserva_id: str, datos: dict) -> dict:
    return _ok(s.confirmar_entrega, reserva_id=reserva_id, **datos)


@app.post("/internal/caja/reservas/{reserva_id}/recibido-cliente")
async def recibido_cliente(reserva_id: str, datos: dict) -> dict:
    return _ok(s.confirmar_recibido, reserva_id=reserva_id, **datos)


# ------------------------------------------------------------------- pagos

@app.get("/internal/pagos/wallets")
async def resolver_wallet(address: str) -> dict:
    return _ok(s.resolver_wallet, wallet_address=address)


@app.post("/internal/pagos/cupos", status_code=201)
async def pedir_cupo(datos: dict) -> dict:
    return _ok(s.pedir_cupo, **datos)


@app.post("/internal/pagos/cupos/{grant_id}/continuar")
async def continuar_cupo(grant_id: str, datos: dict) -> dict:
    return _ok(s.continuar_permiso, grant_id=grant_id, interact_ref=datos.get("interact_ref", ""),
               hash=datos.get("hash", ""))


@app.post("/internal/pagos/cobros", status_code=201)
async def crear_cobro(datos: dict) -> dict:
    return _ok(s.crear_cobro, **datos)


@app.post("/internal/pagos/cotizaciones", status_code=201)
async def cotizar(datos: dict) -> dict:
    url = datos.get("incoming_payment_url")
    if not url and datos.get("reserva_id") in s.ALMACEN.reservas:
        url = s.ALMACEN.reservas[datos["reserva_id"]].incoming_payment_url
    return _ok(s.cotizar, wallet_cliente=datos["wallet_cliente"], incoming_payment_url=url or "")


@app.post("/internal/pagos/aprobaciones", status_code=201)
async def aprobar(datos: dict) -> dict:
    return _ok(s.registrar_aprobacion, **datos)


_PAGOS_HECHOS: dict[str, dict] = {}


@app.post("/internal/pagos/pagos")
async def pagar(datos: dict, idempotency_key: str = Header("")) -> dict:
    clave = idempotency_key or datos["reserva_id"]
    if clave in _PAGOS_HECHOS:
        return _PAGOS_HECHOS[clave]
    r = _ok(s.pagar, reserva_id=datos["reserva_id"])
    _PAGOS_HECHOS[clave] = r
    return r


@app.get("/internal/pagos/saldo")
async def consultar_saldo(whatsapp: str) -> dict:
    return _ok(s.consultar_saldo, whatsapp=whatsapp)


@app.get("/internal/pagos/cobros/estado")
async def estado_cobro(url: str) -> dict:
    return _ok(s.estado_cobro, incoming_payment_url=url)


# ------------------------------------------- páginas simuladas de billetera y Didit

def _pagina(titulo: str, cuerpo: str) -> str:
    return (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            f"<title>{titulo}</title><body style='font-family:system-ui;max-width:28rem;margin:3rem auto;"
            f"padding:0 1rem'><h2>{titulo}</h2>{cuerpo}</body>")


@app.get("/simulador/billetera", response_class=HTMLResponse)
async def billetera(grant_id: str, interact_ref: str) -> str:
    g = s.ALMACEN.grants.get(grant_id)
    if g is None:
        raise HTTPException(404)
    ok = f"{OP_FINISH_URL}?grant_id={grant_id}&interact_ref={interact_ref}&hash=simulado"
    no = f"{OP_FINISH_URL}?grant_id={grant_id}&result=grant_rejected"
    return _pagina("Billetera de prueba", f"<p>Caja de Barrio pide un cupo para pagar tus retiros: hasta "
                   f"<b>{g['limite']:,} {g['moneda']}</b> cada 7 días.</p>"
                   f"<p><a href='{ok}'>Aprobar cupo</a> · <a href='{no}'>Rechazar</a></p>")


async def _enviar_webhook_didit(session_id: str, aprobado: bool) -> None:
    cuerpo = {"session_id": session_id, "vendor_data": session_id,
              "status": "Approved" if aprobado else "Declined"}
    async with httpx.AsyncClient(timeout=120) as cliente:
        r = await cliente.post(DIDIT_CALLBACK_URL, content=json.dumps(cuerpo),
                               headers={"Content-Type": "application/json"})
    log.info("webhook Didit simulado session_id=%s -> %s", session_id, r.status_code)


@app.get("/simulador/didit", response_class=HTMLResponse)
async def didit(session_id: str) -> str:
    return _pagina("Verificación de identidad de prueba",
                   f"<p>Sesión <code>{session_id}</code></p>"
                   f"<p><a href='/simulador/didit/resultado?session_id={session_id}&aprobado=true'>La cara coincide</a>"
                   f" · <a href='/simulador/didit/resultado?session_id={session_id}&aprobado=false'>"
                   f"La cara NO coincide</a></p>")


@app.get("/simulador/didit/resultado", response_class=HTMLResponse)
async def didit_resultado(session_id: str, aprobado: bool, tareas: BackgroundTasks) -> str:
    tareas.add_task(_enviar_webhook_didit, session_id, aprobado)
    return _pagina("Verificación enviada", "<p>Vuelve a WhatsApp.</p>")
