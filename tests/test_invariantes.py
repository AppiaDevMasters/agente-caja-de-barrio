"""Las invariantes de seguridad (sección 6 del contexto) sobre las herramientas simuladas."""

from datetime import timedelta

import pytest

from agente.herramientas import simuladas as s

LAURA = "per_laura"
WALLET_LAURA = "$ilp.interledger-test.dev/laura-cajadebarrio"
WALLET_ANDRES = "$ilp.interledger-test.dev/andres-cajadebarrio"
RUTA_N = (6.2766, -75.5583)


@pytest.fixture(autouse=True)
def almacen_limpio():
    s.reiniciar()


def preparar_hasta_permiso(monto=200_000, wallet=WALLET_LAURA, persona=LAURA, tienda="tie_jaime"):
    r = s.reservar_efectivo(tienda, persona, monto)
    rid = r["reserva_id"]
    assert s.evaluar_riesgo(persona, monto, "573000000001", rid)["decision"] == "permitir"
    cobro = s.crear_cobro(s.WALLET_TIENDA, monto, rid)["incoming_payment_url"]
    quote = s.cotizar(wallet, cobro)
    permiso = s.pedir_permiso(wallet, quote["quote_url"], rid)
    interact_ref = permiso["redirect_url"].split("interact_ref=")[1]
    assert s.continuar_permiso(rid, interact_ref)["ok"]
    return rid, r["codigo_4_digitos"], cobro, quote


def aprobar_cara(rid, aprobado=True):
    sesion = s.crear_sesion_facial(LAURA, "retiro", rid)["session_id"]
    assert s.marcar_face_match(rid, aprobado, sesion)["ok"]


def test_retiro_completo():
    rid, codigo, cobro, quote = preparar_hasta_permiso()
    assert quote["moneda"] == "COP" and quote["debito"] == 200_000 + quote["comision"]
    aprobar_cara(rid)
    assert s.pagar(rid)["estado"] == "completado"
    assert s.estado_cobro(cobro)["completado"] is True
    assert s.confirmar_entrega(rid, codigo) == {"estado": "entregada"}
    tienda = s.ALMACEN.tiendas["tie_jaime"]
    assert tienda.publicado_cop == 600_000 and tienda.reservado_cop == 0


def test_inv1_no_se_entrega_antes_del_pago():
    rid, codigo, _, _ = preparar_hasta_permiso()
    assert "error" in s.confirmar_entrega(rid, codigo)
    assert s.consultar_reserva(rid)["estado"] == "reservada"


def test_inv1_codigo_incorrecto_no_entrega():
    rid, codigo, _, _ = preparar_hasta_permiso()
    aprobar_cara(rid)
    s.pagar(rid)
    otro = "0000" if codigo != "0000" else "1111"
    assert "error" in s.confirmar_entrega(rid, otro)


def test_inv2_no_se_paga_sin_face_match():
    rid, _, cobro, _ = preparar_hasta_permiso()
    assert "error" in s.pagar(rid)
    aprobar_cara(rid, aprobado=False)  # escena de fraude: la cara no coincide
    assert "error" in s.pagar(rid)
    assert s.estado_cobro(cobro)["completado"] is False


def test_inv3_no_se_paga_sin_riesgo():
    rid = s.reservar_efectivo("tie_jaime", LAURA, 100_000)["reserva_id"]
    cobro = s.crear_cobro(s.WALLET_TIENDA, 100_000, rid)["incoming_payment_url"]
    quote = s.cotizar(WALLET_LAURA, cobro)["quote_url"]
    ref = s.pedir_permiso(WALLET_LAURA, quote, rid)["redirect_url"].split("interact_ref=")[1]
    s.continuar_permiso(rid, ref)
    aprobar_cara(rid)
    assert "riesgo" in s.pagar(rid)["error"]


def test_inv4_no_se_paga_sin_grant_aprobado():
    rid = s.reservar_efectivo("tie_jaime", LAURA, 100_000)["reserva_id"]
    s.evaluar_riesgo(LAURA, 100_000, "x", rid)
    cobro = s.crear_cobro(s.WALLET_TIENDA, 100_000, rid)["incoming_payment_url"]
    quote = s.cotizar(WALLET_LAURA, cobro)["quote_url"]
    s.pedir_permiso(WALLET_LAURA, quote, rid)
    aprobar_cara(rid)
    assert "aprobado" in s.pagar(rid)["error"]


def test_inv4_tope_de_la_tienda():
    assert "error" in s.reservar_efectivo("tie_gloria", LAURA, 300_001)


def test_pitufeo_bloquea_al_cuarto_retiro():
    for _ in range(3):
        rid, codigo, _, _ = preparar_hasta_permiso(monto=50_000, tienda="tie_esperanza")
        aprobar_cara(rid)
        s.pagar(rid)
    rid = s.reservar_efectivo("tie_esperanza", LAURA, 50_000)["reserva_id"]
    assert s.evaluar_riesgo(LAURA, 50_000, "x", rid)["decision"] == "bloquear"
    assert s.ALMACEN.personas[LAURA].estado_registro == "bloqueada"
    assert s.ALMACEN.alertas[-1]["regla"] == "pitufeo"


def test_remesa_en_dolares():
    rid, _, _, quote = preparar_hasta_permiso(wallet=WALLET_ANDRES, persona="per_rosa")
    assert quote["moneda"] == "USD"
    assert quote["debito"] == pytest.approx((200_000 + 2_000 + 2_000) / s.COP_POR_USD)


def test_reserva_vencida_libera_efectivo(monkeypatch):
    rid = s.reservar_efectivo("tie_jaime", LAURA, 100_000)["reserva_id"]
    futuro = s.ahora() + timedelta(minutes=16)
    monkeypatch.setattr(s, "ahora", lambda: futuro)
    assert s.consultar_reserva(rid)["estado"] == "vencida"
    assert s.ALMACEN.tiendas["tie_jaime"].reservado_cop == 0


def test_buscar_cajas_ordena_por_distancia_y_filtra_por_efectivo():
    tiendas = s.buscar_cajas_cercanas(*RUTA_N, monto_cop=500_000)["tiendas"]
    # Gloria (250k) y Aranjuez (150k) no tienen 500k libres; los topes también filtran.
    assert {t["id"] for t in tiendas} == {"tie_jaime", "tie_paisa", "tie_esperanza"}
    assert all(t["metros"] <= 1500 for t in tiendas)
    assert tiendas == sorted(tiendas, key=lambda t: t["metros"])
