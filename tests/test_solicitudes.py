"""Solicitudes de tendero: lógica de referencia, backend simulado (/internal y /admin) y /internal/avisos."""

import json

import pytest
from fastapi.testclient import TestClient

from agente import gateway
from agente.herramientas import simuladas as s
from dev import backend_simulado as b

WA = "573001110020"
WALLET_TIENDA = s.WALLET_TIENDA
DATOS = dict(whatsapp=WA, tipo="CC", numero="71234567", nombre_tienda="Tienda Nueva", direccion="Cra 50 #90-01",
             lat=6.277, lon=-75.557, wallet_address=WALLET_TIENDA, efectivo_estimado_cop=500000)


@pytest.fixture(autouse=True)
def limpio():
    s.reiniciar()


def aceptar(whatsapp=WA):
    s.aceptar_politicas(whatsapp, s.POLITICAS_VERSION, "acepto")


def solicitud_en_revision() -> str:
    aceptar()
    sid = s.solicitar_ser_tendero(**DATOS)["solicitud_id"]
    sesion = s.crear_sesion_facial(motivo="alta_tendero", solicitud_id=sid)["session_id"]
    r = s.marcar_face_match(sesion, True)
    assert (r["whatsapp"], r["motivo"], r["estado_solicitud"]) == (WA, "alta_tendero", "en_revision")
    return sid


# ---------------------------------------------------------------- lógica

def test_sin_politicas_no_hay_solicitud():
    assert "políticas" in s.solicitar_ser_tendero(**DATOS)["error"]


def test_ciclo_completo_hasta_ser_tendero():
    sid = solicitud_en_revision()
    assert s.consultar_persona(WA)["rol"] == "solicitante"
    r = s.decidir_solicitud(sid, "aprobar", "Documentos y ubicación verificados.", nivel="basico")
    assert r["whatsapp"] == WA and "APROBADA" in r["aviso"]
    yo = s.consultar_persona(WA)
    assert yo["rol"] == "tendero" and yo["tienda_id"] == r["tienda_id"]
    assert s.publicar_efectivo(r["tienda_id"], 300000)["libre_cop"] == 300000
    assert s.ALMACEN.tiendas[r["tienda_id"]].nivel == "basico"


def test_checks_marcan_duplicados_sin_bloquear():
    sid = solicitud_en_revision()
    checks = {c["clave"]: c for c in s.detalle_solicitud(sid)["checks"]}
    assert checks["face_match"]["estado"] == "ok"
    assert checks["duplicados"]["estado"] == "alerta" and "Tienda Don Jaime" in checks["duplicados"]["detalle"]
    assert checks["wallet_resuelve"]["estado"] == "ok"


def test_didit_rechazado_cierra_la_solicitud():
    aceptar()
    sid = s.solicitar_ser_tendero(**DATOS)["solicitud_id"]
    sesion = s.crear_sesion_facial(motivo="alta_tendero", solicitud_id=sid)["session_id"]
    s.marcar_face_match(sesion, False)
    assert s.consultar_solicitud_tendero(WA)["estado"] == "rechazada"
    assert "error" in s.decidir_solicitud(sid, "aprobar", "Intento de aprobar sin revisión.")


def test_pedir_correccion_y_corregir():
    sid = solicitud_en_revision()
    r = s.decidir_solicitud(sid, "pedir_correccion", "El pin no coincide con la dirección.", campos=["ubicacion"])
    assert r["estado"] == "correccion_pedida" and "ubicacion" in r["aviso"]
    assert s.consultar_solicitud_tendero(WA)["campos_a_corregir"] == ["ubicacion"]
    assert s.corregir_solicitud_tendero(sid, lat=6.2771, lon=-75.5571)["estado"] == "en_revision"


def test_reglas_de_la_decision():
    sid = solicitud_en_revision()
    assert "10 caracteres" in s.decidir_solicitud(sid, "aprobar", "ok")["error"]
    assert "aliado" in s.decidir_solicitud(sid, "aprobar", "Motivo suficiente aquí.", nivel="aliado")["error"]
    assert s.decidir_solicitud(sid, "rechazar", "No cumple los requisitos.")["estado"] == "rechazada"


def test_no_se_duplica_una_solicitud_abierta_ni_un_tendero():
    solicitud_en_revision()
    assert "Ya tiene una solicitud" in s.solicitar_ser_tendero(**DATOS)["error"]
    aceptar("573000000010")
    assert "tendero" in s.solicitar_ser_tendero(**{**DATOS, "whatsapp": "573000000010"})["error"]


# ------------------------------------------------- backend simulado por HTTP

def test_ciclo_por_http_y_aviso_al_agente(monkeypatch):
    avisos = []

    async def capturar(whatsapp, aviso):
        avisos.append((whatsapp, aviso))

    monkeypatch.setattr(b, "SERVICIO_TOKEN", "tok")
    monkeypatch.setattr(b, "avisar_al_agente", capturar)
    api = TestClient(b.app, headers={"X-Servicio-Token": "tok"})
    aceptar()
    sid = api.post("/internal/identidad/solicitudes-tendero", json=DATOS).json()["solicitud_id"]
    sesion = api.post("/internal/identidad/verificaciones",
                      json={"solicitud_id": sid, "motivo": "alta_tendero"}).json()["session_id"]
    didit = api.post("/internal/identidad/webhooks/didit",
                     json={"cuerpo": json.dumps({"session_id": sesion, "status": "Approved"}), "firma": ""}).json()
    assert didit["motivo"] == "alta_tendero" and didit["whatsapp"] == WA
    assert api.get("/admin/solicitudes-tendero", params={"estado": "en_revision"}).json()["total"] == 1
    malo = api.post(f"/admin/solicitudes-tendero/{sid}/aprobar", json={"motivo": "corto"})
    assert malo.status_code == 409
    ok = api.post(f"/admin/solicitudes-tendero/{sid}/aprobar", json={"motivo": "Todo verificado en revisión.",
                                                                   "nivel": "basico"})
    assert ok.status_code == 200 and avisos == [(WA, ok.json()["aviso"])]
    assert api.get("/internal/identidad/personas", params={"whatsapp": WA}).json()["rol"] == "tendero"


# ------------------------------------------------------- /internal/avisos

class Falsas:
    def __init__(self):
        self.recibidos = []

    async def responder(self, usuario, texto):
        self.recibidos.append((usuario, texto))
        return ["ok"]


def test_avisos_exigen_token_y_llegan_a_la_sesion(monkeypatch):
    falsas = Falsas()
    gateway.usar_conversaciones(falsas)
    gateway.PENDIENTES.clear()
    cliente = TestClient(gateway.app)
    aviso = {"whatsapp": WA, "aviso": "Tu tienda quedó activa."}

    monkeypatch.setenv("SERVICIO_TOKEN", "")
    gateway.get_settings.cache_clear()
    assert cliente.post("/internal/avisos", json=aviso, headers={"X-Servicio-Token": ""}).status_code == 401

    monkeypatch.setenv("SERVICIO_TOKEN", "secreto")
    gateway.get_settings.cache_clear()
    assert cliente.post("/internal/avisos", json=aviso, headers={"X-Servicio-Token": "otro"}).status_code == 401
    assert cliente.post("/internal/avisos", json=aviso, headers={"X-Servicio-Token": "secreto"}).status_code == 202
    assert falsas.recibidos == [(WA, "[sistema] Tu tienda quedó activa.")]
    gateway.get_settings.cache_clear()
