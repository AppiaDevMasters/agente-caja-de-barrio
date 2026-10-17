"""Didit sin webhook: la decisión se consulta (LISTO en el chat o página de retorno)."""

import pytest
from fastapi.testclient import TestClient

from agente import gateway
from agente.herramientas import simuladas as s

PERSONA = "573007654321"


@pytest.fixture(autouse=True)
def limpio():
    s.reiniciar()


def sesion_de_alta():
    s.aceptar_politicas(PERSONA, s.POLITICAS_VERSION, "Acepto")
    return s.crear_sesion_facial(whatsapp=PERSONA, motivo="alta")["session_id"]


def test_la_decision_queda_pendiente_hasta_que_se_consulta():
    sid = sesion_de_alta()
    assert s.estado_verificacion(sid)["pendiente"] is True
    s.registrar_decision_didit(sid, True)
    assert s.consultar_persona(PERSONA)["estado_registro"] == "verificando"
    r = s.estado_verificacion(sid)
    assert (r["pendiente"], r["aprobada"], r["motivo"], r["whatsapp"]) == (False, True, "alta", PERSONA)
    yo = s.consultar_persona(PERSONA)
    assert yo["estado_registro"] == "aprobada" and s.consultar_saldo(PERSONA)["saldo"] == 1_000_000


def test_consultar_dos_veces_no_procesa_dos_veces():
    sid = sesion_de_alta()
    s.registrar_decision_didit(sid, True)
    s.estado_verificacion(sid)
    s.estado_verificacion(sid)
    cargas = [m for m in s.ALMACEN.movimientos if m["tipo"] == "carga_inicial"
              and m["wallet_address"] == s.consultar_persona(PERSONA)["wallet_address"]]
    assert len(cargas) == 1


class Falsas:
    def __init__(self):
        self.recibidos = []

    async def responder(self, usuario, texto):
        self.recibidos.append((usuario, texto))
        return ["ok"]


def test_pagina_de_retorno_procesa_y_avisa_en_el_chat():
    falsas = Falsas()
    gateway.usar_conversaciones(falsas)
    cliente = TestClient(gateway.app)
    sid = sesion_de_alta()
    assert "procesando" in cliente.get(f"/didit/retorno?session_id={sid}").text
    assert falsas.recibidos == []
    s.registrar_decision_didit(sid, False)
    assert "Vuelve al chat" in cliente.get(f"/didit/retorno?session_id={sid}").text
    assert falsas.recibidos[-1][0] == PERSONA and "RECHAZADA" in falsas.recibidos[-1][1]
    assert s.consultar_persona(PERSONA)["estado_registro"] == "verificando"
