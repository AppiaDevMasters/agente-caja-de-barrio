"""La prueba de punta a punta (contexto-caja-de-barrio/prueba-punta-a-punta.md) sobre la lógica de referencia."""

import pytest
from fastapi.testclient import TestClient

from agente.herramientas import simuladas as s
from dev import backend_simulado as b

TENDERO, PERSONA = "573001234567", "573007654321"


@pytest.fixture(autouse=True)
def limpio():
    s.reiniciar()


def aceptar(whatsapp):
    s.aceptar_politicas(whatsapp, s.POLITICAS_VERSION, "Acepto")


def didit(**kw):
    sesion = s.crear_sesion_facial(**kw)
    assert "error" not in sesion, sesion
    return s.marcar_face_match(sesion["session_id"], True)


def tendero_activo():
    t = s.registrar_tendero_panel("Tienda La Prueba", "Cra 50 #91-10", 6.2768, -75.5581, "comercio", TENDERO,
                                  "Magno", "Alta de tendero para la prueba.")
    aceptar(TENDERO)
    r = didit(tienda_id=t["tienda_id"], motivo="alta_tendero")
    assert r["estado_tienda"] == "activa" and r["whatsapp"] == TENDERO
    assert s.publicar_efectivo(t["tienda_id"], 800_000)["ok"]
    return t


def persona_registrada():
    aceptar(PERSONA)
    r = didit(whatsapp=PERSONA, motivo="alta")
    assert r["motivo"] == "alta" and r["whatsapp"] == PERSONA
    return s.consultar_persona(PERSONA)


def test_tendero_del_panel_queda_pendiente_hasta_didit():
    t = s.registrar_tendero_panel("Tienda La Prueba", "Cra 50 #91-10", 6.2768, -75.5581, "comercio", TENDERO,
                                  "Magno", "Alta de tendero para la prueba.")
    assert t["estado"] == "pendiente_verificacion" and "verifica tu identidad" in t["aviso"]
    yo = s.consultar_persona(TENDERO)
    assert (yo["rol"], yo["estado_tienda"]) == ("tendero", "pendiente_verificacion")
    assert "activa" in s.publicar_efectivo(t["tienda_id"], 100_000)["error"]
    assert "políticas" in s.crear_sesion_facial(tienda_id=t["tienda_id"], motivo="alta_tendero")["error"]
    assert s.consultar_saldo(TENDERO)["saldo"] == 0


def test_persona_nueva_se_registra_con_didit_y_verifik_sin_escribir_la_cedula():
    assert s.consultar_persona(PERSONA)["rol"] == "no_registrada"
    yo = persona_registrada()
    assert yo["rol"] == "cliente" and yo["estado_registro"] == "aprobada"
    saldo = s.consultar_saldo(PERSONA)
    assert saldo["saldo"] == 1_000_000 and saldo["moneda"] == "COP"
    assert saldo["wallet_address"] == yo["wallet_address"] != ""
    assert saldo["movimientos"][-1]["tipo"] == "carga_inicial"


def test_sin_didit_aprobado_no_hay_registro():
    aceptar(PERSONA)
    sesion = s.crear_sesion_facial(whatsapp=PERSONA, motivo="alta")
    s.marcar_face_match(sesion["session_id"], False)
    yo = s.consultar_persona(PERSONA)
    assert yo["estado_registro"] == "verificando" and "billetera" in s.consultar_saldo(PERSONA)["error"]


def test_retiro_completo_mueve_las_billeteras_virtuales():
    t = tendero_activo()
    yo = persona_registrada()
    sesion = s.crear_sesion_facial(persona_id=yo["persona_id"], motivo="retiro")
    s.marcar_face_match(sesion["session_id"], True)
    tiendas = s.buscar_cajas_cercanas(6.2766, -75.5583, 200_000)["tiendas"]
    assert tiendas[0]["id"] == t["tienda_id"]
    r = s.reservar_efectivo(t["tienda_id"], yo["persona_id"], 200_000)
    rid = r["reserva_id"]
    assert s.evaluar_riesgo(yo["persona_id"], 200_000, PERSONA, rid)["decision"] == "permitir"
    g = s.pedir_cupo(yo["persona_id"], yo["wallet_address"])
    s.continuar_permiso(g["grant_id"], g["redirect_url"].split("interact_ref=")[1])
    cobro = s.crear_cobro(t["wallet_address"], 200_000, rid)
    quote = s.cotizar(yo["wallet_address"], cobro["incoming_payment_url"])
    s.registrar_aprobacion(rid, yo["persona_id"], "APROBAR", "adk")
    assert s.pagar(rid)["estado"] == "completado"
    assert s.consultar_saldo(PERSONA)["saldo"] == 1_000_000 - quote["debito"]
    assert s.consultar_saldo(TENDERO)["saldo"] == 200_000 + r["comision_tendero_cop"]
    assert s.ALMACEN.saldos[s.WALLET_APP_COP] == 2_000
    s.confirmar_entrega(rid, r["codigo_4_digitos"])
    assert s.confirmar_recibido(rid, True, "ya recibí")["estado"] == "entregada"


def test_no_se_paga_sin_saldo():
    t = tendero_activo()
    yo = persona_registrada()
    s.ALMACEN.saldos[yo["wallet_address"]] = 1_000
    sesion = s.crear_sesion_facial(persona_id=yo["persona_id"], motivo="retiro")
    s.marcar_face_match(sesion["session_id"], True)
    rid = s.reservar_efectivo(t["tienda_id"], yo["persona_id"], 100_000)["reserva_id"]
    s.evaluar_riesgo(yo["persona_id"], 100_000, PERSONA, rid)
    g = s.pedir_cupo(yo["persona_id"], yo["wallet_address"])
    s.continuar_permiso(g["grant_id"], g["redirect_url"].split("interact_ref=")[1])
    cobro = s.crear_cobro(t["wallet_address"], 100_000, rid)
    s.cotizar(yo["wallet_address"], cobro["incoming_payment_url"])
    s.registrar_aprobacion(rid, yo["persona_id"], "APROBAR", "adk")
    assert "Saldo insuficiente" in s.pagar(rid)["error"]
    assert s.consultar_reserva(rid)["estado"] == "reservada"


def test_backend_simulado_alta_de_tendero_avisa_y_saldo_por_http(monkeypatch):
    avisos = []

    async def capturar(whatsapp, aviso):
        avisos.append((whatsapp, aviso))

    monkeypatch.setattr(b, "SERVICIO_TOKEN", "tok")
    monkeypatch.setattr(b, "avisar_al_agente", capturar)
    api = TestClient(b.app, headers={"X-Servicio-Token": "tok"})
    r = api.post("/admin/tenderos", json={"nombre_tienda": "Tienda HTTP", "direccion": "Cl 1", "lat": 6.27,
                                          "lon": -75.55, "nivel": "basico", "whatsapp_tendero": TENDERO,
                                          "nombre_tendero": "Magno", "motivo": "Alta por HTTP de prueba."})
    assert r.status_code == 201 and avisos[0][0] == TENDERO
    assert api.get("/internal/pagos/saldo", params={"whatsapp": TENDERO}).json()["saldo"] == 0
    assert api.get("/internal/pagos/saldo", params={"whatsapp": "573000000001"}).json()["saldo"] == 1_000_000
