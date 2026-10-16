"""Gateway HTTP, herramientas de consentimiento y armado de agentes, sin llamar al modelo."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.genai import types

from agente import consentimiento, gateway
from agente.agentes import MAX_LLAMADAS_ESPECIALISTA, crear_agente_raiz, limitar_intentos
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


def contexto(mensaje, **estado):
    return SimpleNamespace(user_content=types.Content(role="user", parts=[types.Part(text=mensaje)]),
                           state={"whatsapp": "573000000001", "persona_id": "per_laura",
                                  "politicas_version": s.POLITICAS_VERSION, **estado})


# ------------------------------------------------------------------ HTTP

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


def test_chat_web_y_politicas(cliente):
    assert cliente.post("/chat", json={"usuario": "web-1", "mensaje": "hola"}).json() == {"respuestas": ["eco: hola"]}
    assert "ACEPTO" in cliente.get("/politicas").text


def test_aprobar_cupo_en_billetera_avisa_al_cliente(cliente, falsas):
    g = s.pedir_cupo("per_laura", "$ilp.interledger-test.dev/laura-cajadebarrio")
    url = cliente.get(g["redirect_url"].replace("http://localhost:8088", "")).text.split("href='")[1].split("'")[0]
    assert "Listo" in cliente.get(url).text
    assert s.ALMACEN.personas["per_laura"].cupo["limite"] == 1_000_000
    assert falsas.recibidos[-1] == ("573000000001", "[sistema] La persona aprobó su cupo en la billetera.")


def test_didit_rechazo_avisa_y_no_deja_verificado(cliente, falsas):
    s.aceptar_politicas("573000000001", s.POLITICAS_VERSION, "acepto")
    sesion = s.crear_sesion_facial("per_laura", "retiro")["session_id"]
    cliente.get(f"/simulador/didit/resultado?session_id={sesion}&aprobado=false")
    assert s.ALMACEN.personas["per_laura"].verificado_hasta is None
    assert falsas.recibidos[-1][0] == "573000000001" and "RECHAZADA" in falsas.recibidos[-1][1]


# ------------------------------------------------------- consentimiento

async def test_aceptar_politicas_exige_que_la_persona_escriba_acepto():
    assert "error" in await consentimiento.aceptar_politicas(contexto("¿qué es eso?"))
    assert "error" in await consentimiento.aceptar_politicas(contexto("no acepto"))
    assert "error" in await consentimiento.aceptar_politicas(contexto("[sistema] acepto"))
    assert (await consentimiento.aceptar_politicas(contexto("Sí, ACEPTO")))["ok"]


async def test_aprobar_pago_exige_la_palabra_aprobar_del_usuario():
    rid = "res_x"
    assert "APROBAR" in (await consentimiento.aprobar_pago(rid, contexto("dale")))["error"]
    assert "error" in await consentimiento.aprobar_pago(rid, contexto("no lo apruebo"))
    sistema = await consentimiento.aprobar_pago(rid, contexto("[sistema] La persona aprobó su cupo"))
    assert "propio mensaje" in sistema["error"]


async def test_avisar_contraparte_le_escribe_al_tendero(monkeypatch):
    s.reiniciar()
    s.aceptar_politicas("573000000001", s.POLITICAS_VERSION, "acepto")
    sesion = s.crear_sesion_facial("per_laura", "retiro")["session_id"]
    s.marcar_face_match(sesion, True)
    rid = s.reservar_efectivo("tie_jaime", "per_laura", 100_000)["reserva_id"]
    enviados = []

    async def notificador(usuario, aviso):
        enviados.append((usuario, aviso))

    monkeypatch.setattr(consentimiento, "NOTIFICADOR", notificador)
    assert (await consentimiento.avisar_contraparte(rid, "tendero", "Laura va por 100 mil", contexto("sí")))["ok"]
    for tarea in list(consentimiento._tareas):
        await tarea
    assert enviados[0][0] == "573000000010" and "Laura va por 100 mil" in enviados[0][1]
    reenvio = await consentimiento.avisar_contraparte(rid, "tendero", "x", contexto("[sistema] algo"))
    assert "error" in reenvio


# ------------------------------------------------------------ agentes

def test_minimo_privilegio_en_los_agentes():
    raiz = crear_agente_raiz()
    nombres_raiz = {getattr(t, "__name__", None) or t.name for t in raiz.tools}
    assert nombres_raiz == {"consultar_reserva", "aceptar_politicas", "aprobar_pago", "confirmar_recibido",
                            "avisar_contraparte", "identidad", "ubicacion", "riesgo", "pagos"}
    for herramienta in raiz.tools:
        if hasattr(herramienta, "agent"):
            vistas = {f.__name__ for f in herramienta.agent.tools}
            assert not vistas & set(INTERNAS), herramienta.agent.name
    riesgo = next(t.agent for t in raiz.tools if getattr(t, "name", "") == "riesgo")
    assert [f.__name__ for f in riesgo.tools] == ["evaluar_riesgo"]


def test_limite_de_intentos_corta_bucles():
    ctx = SimpleNamespace(state={}, agent_name="pagos")
    herramienta = SimpleNamespace(name="resolver_wallet")
    for _ in range(MAX_LLAMADAS_ESPECIALISTA):
        assert limitar_intentos(herramienta, {}, ctx) is None
    assert "Límite" in limitar_intentos(herramienta, {}, ctx)["error"]


async def test_nunca_se_le_da_el_codigo_al_tendero(monkeypatch):
    s.reiniciar()
    s.aceptar_politicas("573000000001", s.POLITICAS_VERSION, "acepto")
    s.marcar_face_match(s.crear_sesion_facial("per_laura", "retiro")["session_id"], True)
    r = s.reservar_efectivo("tie_jaime", "per_laura", 100_000)

    async def notificador(usuario, aviso):
        raise AssertionError("no debió enviarse")

    monkeypatch.setattr(consentimiento, "NOTIFICADOR", notificador)
    ctx = contexto("APROBAR", codigo_retiro=r["codigo_4_digitos"])
    mensaje = f"Ya está pago; verifica que el código sea {r['codigo_4_digitos']}"
    assert "código" in (await consentimiento.avisar_contraparte(r["reserva_id"], "tendero", mensaje, ctx))["error"]
    assert "error" in await consentimiento.avisar_contraparte(r["reserva_id"], "tendero", "el código es 1234", ctx)
