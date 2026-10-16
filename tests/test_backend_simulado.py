"""El backend simulado cumple el contrato: flujo completo por HTTP, errores, token e idempotencia."""

import json

import pytest
from fastapi.testclient import TestClient

from agente.herramientas import simuladas as s
from dev import backend_simulado as b

LAURA = "$ilp.interledger-test.dev/laura-cajadebarrio"
API = "/internal"


@pytest.fixture
def api(monkeypatch):
    s.reiniciar()
    b._PAGOS_HECHOS.clear()
    monkeypatch.setattr(b, "SERVICIO_TOKEN", "tok")
    return TestClient(b.app, headers={"X-Servicio-Token": "tok"})


def ok(r, status=200):
    assert r.status_code == status, r.text
    return r.json()


def test_sin_token_responde_401(api):
    r = TestClient(b.app).get(f"{API}/identidad/personas", params={"whatsapp": "573000000001"})
    assert r.status_code == 401 and r.json()["error"]["codigo"] == "NO_AUTORIZADO"


def test_errores_con_el_formato_del_contrato(api):
    r = api.post(f"{API}/caja/reservas", json={"tienda_id": "tie_jaime", "persona_id": "per_laura", "monto_cop": 1000})
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "SIN_POLITICAS"
    r = api.get(f"{API}/caja/reservas/res_no_existe")
    assert r.status_code == 404 and r.json()["error"]["codigo"] == "NO_ENCONTRADO"


def test_retiro_completo_por_http(api):
    assert ok(api.get(f"{API}/identidad/personas", params={"whatsapp": "573000000010"}))["rol"] == "tendero"
    ok(api.post(f"{API}/identidad/politicas/aceptaciones",
                json={"whatsapp": "573000000001", "version": s.POLITICAS_VERSION, "texto_usuario": "Acepto"}), 201)
    sesion = ok(api.post(f"{API}/identidad/verificaciones", json={"persona_id": "per_laura", "motivo": "retiro"}), 201)
    didit = ok(api.post(f"{API}/identidad/webhooks/didit", json={
        "cuerpo": json.dumps({"session_id": sesion["session_id"], "status": "Approved"}), "firma": ""}))
    assert didit["procesado"] and didit["whatsapp"] == "573000000001"

    tiendas = ok(api.get(f"{API}/mapa/tiendas/cercanas",
                         params={"lat": 6.2766, "lon": -75.5583, "monto_cop": 200000}))["tiendas"]
    assert tiendas[0]["id"] == "tie_jaime" and tiendas[0]["comision_plataforma_cop"] == 2000
    res = ok(api.post(f"{API}/caja/reservas",
                      json={"tienda_id": "tie_jaime", "persona_id": "per_laura", "monto_cop": 200000}), 201)
    rid = res["reserva_id"]
    assert ok(api.post(f"{API}/caja/reservas/{rid}/riesgo", json={
        "persona_id": "per_laura", "monto_cop": 200000, "dispositivo": "573000000001"}))["decision"] == "permitir"

    cupo = ok(api.post(f"{API}/pagos/cupos", json={"persona_id": "per_laura", "wallet_cliente": LAURA}), 201)
    ref = cupo["redirect_url"].split("interact_ref=")[1]
    assert ok(api.post(f"{API}/pagos/cupos/{cupo['grant_id']}/continuar",
                       json={"interact_ref": ref, "hash": "x"}))["whatsapp"] == "573000000001"
    cobro = ok(api.post(f"{API}/pagos/cobros", json={
        "reserva_id": rid, "wallet_tienda": s.WALLET_TIENDA, "monto_cop": 200000}), 201)
    quote = ok(api.post(f"{API}/pagos/cotizaciones", json={"reserva_id": rid, "wallet_cliente": LAURA}), 201)
    assert quote["debito"] == 200000 + res["comision_tendero_cop"] + 2000

    sin_aprobar = api.post(f"{API}/pagos/pagos", json={"reserva_id": rid}, headers={"Idempotency-Key": rid})
    assert sin_aprobar.status_code == 409 and sin_aprobar.json()["error"]["codigo"] == "SIN_APROBACION"
    ok(api.post(f"{API}/pagos/aprobaciones", json={
        "reserva_id": rid, "persona_id": "per_laura", "texto_usuario": "APROBAR", "canal": "whatsapp"}), 201)
    pago = ok(api.post(f"{API}/pagos/pagos", json={"reserva_id": rid}, headers={"Idempotency-Key": rid}))
    assert pago["estado"] == "completado"
    otra_vez = ok(api.post(f"{API}/pagos/pagos", json={"reserva_id": rid}, headers={"Idempotency-Key": rid}))
    assert otra_vez == pago and s.ALMACEN.personas["per_laura"].cupo["usado"] == quote["debito"]
    assert ok(api.get(f"{API}/pagos/cobros/estado", params={"url": cobro["incoming_payment_url"]}))["completado"]

    malo = api.post(f"{API}/caja/reservas/{rid}/entrega-tendero", json={"codigo": "x"})
    assert malo.json()["error"]["codigo"] == "CODIGO_INCORRECTO"
    ok(api.post(f"{API}/caja/reservas/{rid}/entrega-tendero", json={"codigo": res["codigo_4_digitos"]}))
    fin = ok(api.post(f"{API}/caja/reservas/{rid}/recibido-cliente", json={"recibido": True, "texto_usuario": "sí"}))
    assert fin["estado"] == "entregada"


def test_webhook_didit_intermedio_se_ignora(api):
    r = ok(api.post(f"{API}/identidad/webhooks/didit",
                    json={"cuerpo": json.dumps({"session_id": "x", "status": "In Progress"}), "firma": ""}))
    assert r == {"procesado": False, "ignorado": "In Progress"}
