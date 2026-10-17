"""El número de quien escribe sale de la sesión: el modelo no puede cambiarlo."""

from types import SimpleNamespace

from agente.agentes import limitar_intentos


def contexto(whatsapp):
    return SimpleNamespace(state={"whatsapp": whatsapp}, agent_name="identidad")


def test_el_modelo_no_puede_agregar_el_57():
    args = {"whatsapp": "573506477716", "motivo": "alta"}
    assert limitar_intentos(SimpleNamespace(name="crear_sesion_facial"), args, contexto("3506477716")) is None
    assert args["whatsapp"] == "3506477716"


def test_sin_whatsapp_en_los_argumentos_no_se_toca_nada():
    args = {"reserva_id": "res_1"}
    limitar_intentos(SimpleNamespace(name="consultar_reserva"), args, contexto("3506477716"))
    assert args == {"reserva_id": "res_1"}
