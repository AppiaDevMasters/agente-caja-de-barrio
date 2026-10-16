"""Gateway HTTP y armado de agentes, sin llamar al modelo."""

import pytest
from fastapi.testclient import TestClient

from agente import gateway
from agente.agentes import USUARIO_POR_RESERVA, crear_agente_raiz
from agente.herramientas import INTERNAS, simuladas as s


class ConversacionesFalsas:
    def __init__(self):
        self.recibidos = []

    async def responder(self, usuario, texto):
        self.recibidos.append((usuario, texto))
        return [f"eco: {texto}"]


@pytest.fixture
def falsas(monkeypatch):
    s.reiniciar()
    gateway.PENDIENTES.clear()
    c = ConversacionesFalsas()
    gateway.usar_conversaciones(c)
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "secreto")
    gateway.get_settings.cache_clear()
    yield c
    gateway.get_settings.cache_clear()


@pytest.fixture
def cliente(falsas):
    return TestClient(gateway.app)


def test_health(cliente):
    assert cliente.get("/health").json() == {"ok": True, "modo_herramientas": "simulado"}


def test_verificacion_webhook_whatsapp(cliente):
    q = {"hub.mode": "subscribe", "hub.verify_token": "secreto", "hub.challenge": "123"}
    assert cliente.get("/webhook/whatsapp", params=q).text == "123"
    q["hub.verify_token"] = "otro"
    assert cliente.get("/webhook/whatsapp", params=q).status_code == 403


def test_whatsapp_ubicacion_llega_como_texto(cliente, falsas):
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"from": "573000000001", "type": "location", "location": {"latitude": 6.27, "longitude": -75.55}}]}}]}]}
    assert cliente.post("/webhook/whatsapp", json=payload).status_code == 200
    assert falsas.recibidos == [("573000000001", "[ubicación] lat=6.27, lon=-75.55")]


def test_chat_web(cliente):
    assert cliente.post("/chat", json={"usuario": "web-1", "mensaje": "hola"}).json() == {"respuestas": ["eco: hola"]}


def test_aprobacion_en_billetera_avisa_al_agente(cliente, falsas):
    rid = s.reservar_efectivo("tie_jaime", "per_laura", 100_000)["reserva_id"]
    cobro = s.crear_cobro(s.WALLET_TIENDA, 100_000, rid)["incoming_payment_url"]
    quote = s.cotizar("$ilp.interledger-test.dev/laura-cajadebarrio", cobro)["quote_url"]
    url = s.pedir_permiso("$ilp.interledger-test.dev/laura-cajadebarrio", quote, rid)["redirect_url"]
    USUARIO_POR_RESERVA[rid] = "web-laura"
    ref = url.split("interact_ref=")[1]
    assert "Listo" in cliente.get(f"/op/finish?reserva_id={rid}&interact_ref={ref}").text
    assert s.ALMACEN.reservas[rid].grant_aprobado
    assert falsas.recibidos[-1][0] == "web-laura" and "[sistema]" in falsas.recibidos[-1][1]
    assert cliente.get("/chat/pendientes?usuario=web-laura").json()["respuestas"]


def test_didit_simulado_rechazo_marca_face_match(cliente, falsas):
    rid = s.reservar_efectivo("tie_jaime", "per_laura", 100_000)["reserva_id"]
    sesion = s.crear_sesion_facial("per_laura", "retiro", rid)["session_id"]
    USUARIO_POR_RESERVA[rid] = "web-laura"
    cliente.get(f"/simulador/didit/resultado?session_id={sesion}&aprobado=false")
    assert s.ALMACEN.reservas[rid].face_match_ok is False
    assert "RECHAZADA" in falsas.recibidos[-1][1]


def test_minimo_privilegio_en_los_agentes():
    raiz = crear_agente_raiz()
    nombres_raiz = {getattr(t, "__name__", None) or t.name for t in raiz.tools}
    assert nombres_raiz == {"consultar_reserva", "identidad", "ubicacion", "riesgo", "pagos"}
    for herramienta in raiz.tools:
        if hasattr(herramienta, "agent"):
            vistas = {f.__name__ for f in herramienta.agent.tools}
            assert not vistas & set(INTERNAS), herramienta.agent.name
    riesgo = next(t.agent for t in raiz.tools if getattr(t, "name", "") == "riesgo")
    assert [f.__name__ for f in riesgo.tools] == ["evaluar_riesgo"]


def test_limite_de_intentos_corta_bucles():
    from types import SimpleNamespace

    from agente.agentes import MAX_LLAMADAS_ESPECIALISTA, limitar_intentos

    contexto = SimpleNamespace(state={}, agent_name="pagos")
    herramienta = SimpleNamespace(name="resolver_wallet")
    for _ in range(MAX_LLAMADAS_ESPECIALISTA):
        assert limitar_intentos(herramienta, {}, contexto) is None
    assert "Límite" in limitar_intentos(herramienta, {}, contexto)["error"]
