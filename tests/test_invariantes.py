"""Invariantes de seguridad y reglas de oro sobre las herramientas simuladas."""

from datetime import timedelta

import pytest

from agente.herramientas import simuladas as s

LAURA, WA_LAURA = "per_laura", "573000000001"
ROSA, WA_ROSA = "per_rosa", "573000000002"
WALLET_LAURA = "$ilp.interledger-test.dev/laura-cajadebarrio"
WALLET_ANDRES = "$ilp.interledger-test.dev/andres-cajadebarrio"
RUTA_N = (6.2766, -75.5583)


@pytest.fixture(autouse=True)
def almacen_limpio():
    s.reiniciar()


def aceptar(whatsapp=WA_LAURA):
    assert s.aceptar_politicas(whatsapp, s.POLITICAS_VERSION, "Acepto")["ok"]


def verificar(persona=LAURA, aprobado=True):
    sesion = s.crear_sesion_facial(persona, "retiro")["session_id"]
    assert s.marcar_face_match(sesion, aprobado)["ok"]


def aprobar_cupo(persona=LAURA, wallet=WALLET_LAURA):
    g = s.pedir_cupo(persona, wallet)
    ref = g["redirect_url"].split("interact_ref=")[1]
    assert s.continuar_permiso(g["grant_id"], ref)["ok"]


def cliente_listo(persona=LAURA, whatsapp=WA_LAURA, wallet=WALLET_LAURA):
    aceptar(whatsapp)
    verificar(persona)
    aprobar_cupo(persona, wallet)


def hasta_cotizar(monto=200_000, persona=LAURA, wallet=WALLET_LAURA, tienda="tie_jaime", riesgo=True):
    r = s.reservar_efectivo(tienda, persona, monto)
    rid = r["reserva_id"]
    if riesgo:
        assert s.evaluar_riesgo(persona, monto, "wa", rid)["decision"] == "permitir"
    cobro = s.crear_cobro(s.WALLET_TIENDA, monto, rid)
    quote = s.cotizar(wallet, cobro["incoming_payment_url"])
    return rid, r["codigo_4_digitos"], cobro, quote


def pagado(**kw):
    rid, codigo, cobro, quote = hasta_cotizar(**kw)
    assert s.registrar_aprobacion(rid, kw.get("persona", LAURA), "APROBAR", "whatsapp")["ok"]
    assert s.pagar(rid)["estado"] == "completado"
    return rid, codigo, cobro, quote


# ------------------------------------------------------------- flujo completo

def test_retiro_completo_con_doble_confirmacion():
    cliente_listo()
    rid, codigo, cobro, quote = pagado()
    assert quote["debito"] == quote["desglose_cop"]["total"]
    assert s.estado_cobro(cobro["incoming_payment_url"])["completado"] is True
    assert s.estado_cobro(cobro["cobro_plataforma_url"])["completado"] is True
    assert s.confirmar_entrega(rid, codigo) == {"estado": "pagada", "falta_confirmacion_cliente": True}
    assert s.confirmar_recibido(rid, True, "sí, ya me lo dieron")["estado"] == "entregada"
    tienda = s.ALMACEN.tiendas["tie_jaime"]
    assert tienda.publicado_cop == 600_000 and tienda.reservado_cop == 0
    assert [c["parte"] for c in s.ALMACEN.confirmaciones_entrega] == ["tendero", "cliente"]


def test_la_entrega_se_cierra_igual_si_confirma_primero_el_cliente():
    cliente_listo()
    rid, codigo, _, _ = pagado()
    assert s.confirmar_recibido(rid, True, "recibí")["falta_confirmacion_tendero"] is True
    assert s.confirmar_entrega(rid, codigo)["estado"] == "entregada"


def test_cliente_dice_que_no_recibio_abre_disputa():
    cliente_listo()
    rid, codigo, _, _ = pagado()
    assert s.confirmar_recibido(rid, False, "no me dieron nada")["estado"] == "en_disputa"
    assert s.ALMACEN.alertas[-1]["regla"] == "entrega_no_recibida"
    assert "error" in s.confirmar_entrega(rid, codigo)


# --------------------------------------------------- regla 5: políticas y aprobación

def test_sin_politicas_no_se_verifica_ni_se_reserva():
    assert "error" in s.crear_sesion_facial(LAURA, "retiro")
    assert "error" in s.reservar_efectivo("tie_jaime", LAURA, 100_000)
    assert s.consultar_persona(WA_LAURA)["politicas_aceptadas"] is False
    aceptar()
    assert s.consultar_persona(WA_LAURA)["politicas_aceptadas"] is True
    assert s.ALMACEN.aceptaciones_politicas[0]["texto_usuario"] == "Acepto"


def test_no_se_paga_sin_aprobar_en_el_chat():
    cliente_listo()
    rid, _, cobro, _ = hasta_cotizar()
    assert "aprobar" in s.pagar(rid)["error"]
    assert s.estado_cobro(cobro["incoming_payment_url"])["completado"] is False


def test_la_aprobacion_queda_registrada_con_el_texto():
    cliente_listo()
    rid, _, _, quote = hasta_cotizar()
    s.registrar_aprobacion(rid, LAURA, "APROBAR", "whatsapp")
    registro = s.ALMACEN.aprobaciones_pago[-1]
    assert registro["reserva_id"] == rid and registro["texto_usuario"] == "APROBAR"
    assert registro["debito"] == quote["debito"]


def test_no_se_paga_sin_cupo_ni_por_encima_del_cupo():
    aceptar()
    verificar()
    rid, _, _, _ = hasta_cotizar()
    s.registrar_aprobacion(rid, LAURA, "aprobar", "whatsapp")
    assert "cupo" in s.pagar(rid)["error"]
    aprobar_cupo()
    s.ALMACEN.personas[LAURA].cupo["usado"] = s.CUPO_POR_MONEDA["COP"] - 1_000
    assert "cupo" in s.pagar(rid)["error"]


# ------------------------------------------------------ regla 2: Didit primero

def test_sin_verificacion_de_identidad_no_se_reserva():
    aceptar()
    assert "Didit" in s.reservar_efectivo("tie_jaime", LAURA, 100_000)["error"]


def test_escena_de_fraude_la_cara_no_coincide():
    aceptar()
    verificar(aprobado=False)
    assert "error" in s.reservar_efectivo("tie_jaime", LAURA, 100_000)
    assert s.ALMACEN.alertas[-1]["regla"] == "verificacion_facial_fallida"


def test_la_verificacion_vence(monkeypatch):
    aceptar()
    verificar()
    futuro = s.ahora() + timedelta(minutes=31)
    monkeypatch.setattr(s, "ahora", lambda: futuro)
    assert "Didit" in s.reservar_efectivo("tie_jaime", LAURA, 100_000)["error"]


# ------------------------------------------------------ invariantes originales

def test_inv1_no_se_entrega_antes_del_pago():
    cliente_listo()
    rid, codigo, _, _ = hasta_cotizar()
    assert "error" in s.confirmar_entrega(rid, codigo)
    assert "error" in s.confirmar_recibido(rid, True, "sí")


def test_inv1_codigo_incorrecto_no_entrega():
    cliente_listo()
    rid, codigo, _, _ = pagado()
    otro = "0000" if codigo != "0000" else "1111"
    assert "error" in s.confirmar_entrega(rid, otro)


def test_inv3_no_se_paga_sin_riesgo():
    cliente_listo()
    rid, _, _, _ = hasta_cotizar(riesgo=False)
    s.registrar_aprobacion(rid, LAURA, "aprobar", "whatsapp")
    assert "riesgo" in s.pagar(rid)["error"]


def test_inv4_tope_de_la_tienda():
    cliente_listo()
    assert "error" in s.reservar_efectivo("tie_gloria", LAURA, 300_001)


def test_pitufeo_bloquea_al_cuarto_retiro():
    cliente_listo()
    for _ in range(3):
        pagado(monto=50_000, tienda="tie_esperanza")
    rid = s.reservar_efectivo("tie_esperanza", LAURA, 50_000)["reserva_id"]
    assert s.evaluar_riesgo(LAURA, 50_000, "x", rid)["decision"] == "bloquear"
    assert s.ALMACEN.personas[LAURA].estado_registro == "bloqueada"
    assert s.ALMACEN.alertas[-1]["regla"] == "pitufeo"


def test_reserva_vencida_libera_efectivo(monkeypatch):
    cliente_listo()
    rid = s.reservar_efectivo("tie_jaime", LAURA, 100_000)["reserva_id"]
    futuro = s.ahora() + timedelta(minutes=16)
    monkeypatch.setattr(s, "ahora", lambda: futuro)
    assert s.consultar_reserva(rid)["estado"] == "vencida"
    assert s.ALMACEN.tiendas["tie_jaime"].reservado_cop == 0


# ----------------------------------------------------- regla 4: comisiones

@pytest.mark.parametrize("monto,libre,tendero", [
    (100_000, 1_000_000, 1_200),   # 10% del efectivo: 1,2%
    (500_000, 1_000_000, 10_000),  # 50%: 2,0%
    (900_000, 1_000_000, 25_200),  # 90%: 2,8%
    (50_000, 1_000_000, 1_000),    # mínimo
])
def test_comision_del_tendero_segun_su_liquidez(monto, libre, tendero):
    c = s.calcular_comisiones(monto, libre)
    assert c["comision_tendero_cop"] == tendero
    assert c["comision_plataforma_cop"] == round(monto * 0.01)
    assert c["total_cop"] == monto + tendero + c["comision_plataforma_cop"]


def test_cobros_separan_tienda_y_caja_de_barrio():
    cliente_listo()
    rid, _, cobro, _ = hasta_cotizar()
    r = s.ALMACEN.reservas[rid]
    assert cobro["tienda_recibe_cop"] == 200_000 + r.comision_tendero_cop
    assert cobro["caja_de_barrio_recibe_cop"] == 2_000


def test_remesa_en_dolares():
    cliente_listo(ROSA, WA_ROSA, WALLET_ANDRES)
    _, _, _, quote = hasta_cotizar(persona=ROSA, wallet=WALLET_ANDRES)
    assert quote["moneda"] == "USD"
    assert quote["debito"] == pytest.approx(quote["desglose_cop"]["total"] / s.COP_POR_USD, abs=0.01)


# --------------------------------------------------- regla 1: ambas partes

def test_el_tendero_se_identifica_por_su_whatsapp():
    tendero = s.consultar_persona("573000000010")
    assert tendero["rol"] == "tendero" and tendero["tienda_id"] == "tie_jaime"
    assert s.consultar_persona(WA_LAURA)["rol"] == "cliente"
    assert s.consultar_persona("573999999999")["rol"] == "no_registrada"


def test_la_reserva_trae_el_whatsapp_de_ambas_partes():
    cliente_listo()
    rid, _, _, _ = hasta_cotizar()
    r = s.consultar_reserva(rid)
    assert (r["whatsapp_cliente"], r["whatsapp_tendero"]) == (WA_LAURA, "573000000010")
    assert s.reservas_de_tienda("tie_jaime")["reservas"][0]["reserva_id"] == rid


def test_buscar_cajas_trae_comisiones_y_ordena_por_distancia():
    tiendas = s.buscar_cajas_cercanas(*RUTA_N, monto_cop=500_000)["tiendas"]
    assert {t["id"] for t in tiendas} == {"tie_jaime", "tie_paisa", "tie_esperanza"}
    assert tiendas[0]["id"] == "tie_jaime"
    assert tiendas == sorted(tiendas, key=lambda t: t["metros"])
    assert all(t["comision_plataforma_cop"] == 5_000 for t in tiendas)
