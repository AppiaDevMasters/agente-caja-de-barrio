"""Herramientas simuladas en memoria.

Replican nombre, entradas y salidas de las herramientas de los servidores MCP
(mcp-pagos, mcp-mapa, mcp-caja, mcp-identidad) para poder probar el agente sin
que esos servidores existan todavía. Las invariantes de seguridad (sección 6 del
contexto) se validan aquí en código, igual que deberán hacerlo los MCP reales.

Las herramientas nunca lanzan excepciones al modelo: devuelven {"error": ...}
para que el agente le explique a la persona qué pasó.
"""

from __future__ import annotations

import math
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from agente.config import get_settings

VIGENCIA_RESERVA = timedelta(minutes=15)
VIGENCIA_QUOTE = timedelta(minutes=10)
VENTANA_PITUFEO = timedelta(minutes=60)
MAX_RETIROS_EN_VENTANA = 3

TOPE_TIENDA_COP = {"basico": 300_000, "comercio": 1_000_000, "aliado": 3_000_000}
TOPE_PERSONA_COP = {1: 500_000, 2: 2_000_000}

# Tasa fija para simular la conversión de la remesa.
COP_POR_USD = 4_000
COMISION_FIJA_COP = 2_000
COMISION_PORCENTAJE = 0.01

WALLET_TIENDA = "$ilp.interledger-test.dev/tienda-cajadebarrio"
WALLETS = {
    "$ilp.interledger-test.dev/laura-cajadebarrio": ("COP", 2),
    "$ilp.interledger-test.dev/andres-cajadebarrio": ("USD", 2),
    WALLET_TIENDA: ("COP", 2),
    "$ilp.interledger-test.dev/app-cajadebarrio": ("EUR", 2),
}


def ahora() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Persona:
    id: str
    whatsapp: str
    nombre: str
    cedula: str
    wallet_address: str
    nivel: int = 1
    estado_registro: str = "aprobada"


@dataclass
class Tienda:
    id: str
    nombre: str
    direccion: str
    lat: float
    lon: float
    nivel: str
    wallet_address: str = WALLET_TIENDA
    estado: str = "activa"
    publicado_cop: int = 0
    reservado_cop: int = 0

    @property
    def libre_cop(self) -> int:
        return self.publicado_cop - self.reservado_cop


@dataclass
class Reserva:
    id: str
    tienda_id: str
    persona_id: str
    monto_cop: int
    codigo: str
    creada_en: datetime
    vence_en: datetime
    estado: str = "reservada"
    riesgo_ok: bool = False
    face_match_ok: bool = False
    incoming_payment_url: Optional[str] = None
    quote_url: Optional[str] = None
    grant_aprobado: bool = False
    outgoing_payment_id: Optional[str] = None
    pagada_en: Optional[datetime] = None
    entregado_en: Optional[datetime] = None


@dataclass
class Almacen:
    personas: dict[str, Persona] = field(default_factory=dict)
    tiendas: dict[str, Tienda] = field(default_factory=dict)
    reservas: dict[str, Reserva] = field(default_factory=dict)
    cobros: dict[str, dict] = field(default_factory=dict)
    quotes: dict[str, dict] = field(default_factory=dict)
    permisos: dict[str, dict] = field(default_factory=dict)
    sesiones_faciales: dict[str, dict] = field(default_factory=dict)
    alertas: list[dict] = field(default_factory=list)


ALMACEN = Almacen()


def _nuevo_id(prefijo: str) -> str:
    return f"{prefijo}_{secrets.token_hex(4)}"


def reiniciar() -> None:
    """Deja el almacén con los datos semilla de la demo."""
    global ALMACEN
    ALMACEN = Almacen()
    for p in [
        Persona("per_laura", "573000000001", "Laura Gómez", "1036123456",
                "$ilp.interledger-test.dev/laura-cajadebarrio"),
        Persona("per_rosa", "573000000002", "Rosa Restrepo", "43123456",
                "$ilp.interledger-test.dev/andres-cajadebarrio"),
    ]:
        ALMACEN.personas[p.id] = p
    # Tiendas semilla en Aranjuez, Medellín (cerca de Ruta N).
    for t in [
        Tienda("tie_jaime", "Tienda Don Jaime", "Cra 50 #92-15", 6.27795, -75.55860, "comercio", publicado_cop=800_000),
        Tienda("tie_gloria", "Tienda Doña Gloria", "Cl 93 #49-40", 6.28010, -75.55710, "basico", publicado_cop=250_000),
        Tienda("tie_paisa", "Minimercado El Paisa", "Cra 51 #90-22", 6.27560, -75.55790, "comercio", publicado_cop=600_000),
        Tienda("tie_esperanza", "Granero La Esperanza", "Cl 95 #50-10", 6.28220, -75.55640, "aliado", publicado_cop=1_500_000),
        Tienda("tie_aranjuez", "Autoservicio Aranjuez", "Cra 49 #88-05", 6.27310, -75.55520, "basico", publicado_cop=150_000),
    ]:
        ALMACEN.tiendas[t.id] = t


reiniciar()


def _metros(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)))


def _reserva_vigente(reserva_id: str) -> Reserva | dict:
    r = ALMACEN.reservas.get(reserva_id)
    if r is None:
        return {"error": f"No existe la reserva {reserva_id}."}
    if r.estado == "reservada" and ahora() > r.vence_en:
        r.estado = "vencida"
        ALMACEN.tiendas[r.tienda_id].reservado_cop -= r.monto_cop
    return r


# ---------------------------------------------------------------- mcp-identidad

def consultar_persona(whatsapp: str) -> dict:
    """Busca a la persona registrada con ese número de WhatsApp.

    Args:
        whatsapp: Número de WhatsApp con indicativo, solo dígitos (ej. 573001234567).
    """
    for p in ALMACEN.personas.values():
        if p.whatsapp == whatsapp:
            return {"persona_id": p.id, "nombre": p.nombre, "estado_registro": p.estado_registro,
                    "nivel": p.nivel, "wallet_address": p.wallet_address}
    return {"persona_id": None, "estado_registro": "no_registrada"}


def verificar_cedula(tipo: str, numero: str) -> dict:
    """Valida una cédula colombiana (CC) o un PPT contra la registraduría (simulado).

    Args:
        tipo: "CC" o "PPT".
        numero: Número del documento, solo dígitos.
    """
    if tipo not in ("CC", "PPT"):
        return {"error": "El tipo de documento debe ser CC o PPT."}
    valida = numero.isdigit() and 6 <= len(numero) <= 10
    return {"valida": valida, "nombre_completo": "PERSONA DE PRUEBA" if valida else None}


def crear_sesion_facial(persona_id: str, motivo: str, reserva_id: Optional[str] = None) -> dict:
    """Crea una sesión de prueba de vida y face match (Didit simulado).

    Args:
        persona_id: Id de la persona a verificar.
        motivo: "alta" (registro) o "retiro" (en el mostrador).
        reserva_id: Reserva asociada cuando el motivo es "retiro".
    """
    if persona_id not in ALMACEN.personas:
        return {"error": f"No existe la persona {persona_id}."}
    if motivo == "retiro" and not reserva_id:
        return {"error": "Para un retiro se necesita la reserva_id."}
    session_id = _nuevo_id("did")
    ALMACEN.sesiones_faciales[session_id] = {
        "persona_id": persona_id, "motivo": motivo, "reserva_id": reserva_id, "aprobada": None, "score": None,
    }
    base = get_settings().public_base_url
    return {"session_id": session_id, "url_verificacion": f"{base}/simulador/didit?session_id={session_id}"}


def estado_verificacion(session_id: str) -> dict:
    """Consulta el resultado de una sesión de verificación facial.

    Args:
        session_id: Id de la sesión devuelto por crear_sesion_facial.
    """
    s = ALMACEN.sesiones_faciales.get(session_id)
    if s is None:
        return {"error": f"No existe la sesión {session_id}."}
    return {"aprobada": s["aprobada"], "score": s["score"], "pendiente": s["aprobada"] is None}


# --------------------------------------------------------------------- mcp-mapa

def buscar_cajas_cercanas(lat: float, lon: float, monto_cop: int, radio_m: int = 1500) -> dict:
    """Encuentra hasta 3 tiendas verificadas cercanas con efectivo libre suficiente.

    Args:
        lat: Latitud de la persona.
        lon: Longitud de la persona.
        monto_cop: Monto a retirar en pesos colombianos (entero).
        radio_m: Radio de búsqueda en metros.
    """
    candidatas = []
    for t in ALMACEN.tiendas.values():
        if t.estado != "activa" or t.libre_cop < monto_cop or TOPE_TIENDA_COP[t.nivel] < monto_cop:
            continue
        m = _metros(lat, lon, t.lat, t.lon)
        if m <= radio_m:
            candidatas.append({"id": t.id, "nombre": t.nombre, "metros": m, "lat": t.lat, "lon": t.lon,
                               "wallet_address": t.wallet_address})
    candidatas.sort(key=lambda c: c["metros"])
    return {"tiendas": candidatas[:3]}


def detalle_tienda(tienda_id: str) -> dict:
    """Devuelve los datos de la tienda para enviar el pin por WhatsApp.

    Args:
        tienda_id: Id de la tienda.
    """
    t = ALMACEN.tiendas.get(tienda_id)
    if t is None:
        return {"error": f"No existe la tienda {tienda_id}."}
    return {"id": t.id, "nombre": t.nombre, "direccion": t.direccion, "lat": t.lat, "lon": t.lon,
            "nivel": t.nivel, "wallet_address": t.wallet_address}


def publicar_efectivo(tienda_id: str, monto_cop: int) -> dict:
    """El tendero publica cuánto efectivo tiene disponible hoy.

    Args:
        tienda_id: Id de la tienda.
        monto_cop: Efectivo total disponible para retiros, en pesos.
    """
    t = ALMACEN.tiendas.get(tienda_id)
    if t is None:
        return {"error": f"No existe la tienda {tienda_id}."}
    if monto_cop < t.reservado_cop:
        return {"error": "No puede publicar menos de lo que ya está reservado."}
    t.publicado_cop = monto_cop
    return {"ok": True, "libre_cop": t.libre_cop}


# --------------------------------------------------------------------- mcp-caja

def reservar_efectivo(tienda_id: str, persona_id: str, monto_cop: int) -> dict:
    """Aparta el efectivo en la tienda y genera el código de retiro de 4 dígitos.

    Args:
        tienda_id: Id de la tienda elegida.
        persona_id: Id de la persona que retira.
        monto_cop: Monto en pesos (entero).
    """
    t = ALMACEN.tiendas.get(tienda_id)
    p = ALMACEN.personas.get(persona_id)
    if t is None or p is None:
        return {"error": "Tienda o persona inexistente."}
    if p.estado_registro != "aprobada":
        return {"error": f"La persona no puede retirar (estado {p.estado_registro})."}
    if t.estado != "activa":
        return {"error": "La tienda no está recibiendo retiros."}
    if monto_cop <= 0:
        return {"error": "El monto debe ser positivo."}
    if monto_cop > TOPE_TIENDA_COP[t.nivel]:
        return {"error": f"La tienda solo entrega hasta {TOPE_TIENDA_COP[t.nivel]} COP por retiro."}
    if t.libre_cop < monto_cop:
        return {"error": "La tienda ya no tiene ese efectivo libre."}
    t.reservado_cop += monto_cop
    r = Reserva(_nuevo_id("res"), tienda_id, persona_id, monto_cop, f"{secrets.randbelow(10_000):04d}",
                ahora(), ahora() + VIGENCIA_RESERVA)
    ALMACEN.reservas[r.id] = r
    return {"reserva_id": r.id, "codigo_4_digitos": r.codigo, "vence_en": r.vence_en.isoformat()}


def consultar_reserva(reserva_id: str) -> dict:
    """Estado de una reserva y qué pasos del retiro ya se completaron.

    Args:
        reserva_id: Id de la reserva.
    """
    r = _reserva_vigente(reserva_id)
    if isinstance(r, dict):
        return r
    return {
        "reserva_id": r.id, "estado": r.estado, "tienda_id": r.tienda_id, "monto_cop": r.monto_cop,
        "vence_en": r.vence_en.isoformat(),
        "pasos": {"riesgo_ok": r.riesgo_ok, "cobro_creado": r.incoming_payment_url is not None,
                  "cotizado": r.quote_url is not None, "permiso_aprobado": r.grant_aprobado,
                  "face_match_ok": r.face_match_ok, "pagada": r.estado in ("pagada", "entregada"),
                  "entregada": r.estado == "entregada"},
    }


def cancelar_reserva(reserva_id: str, motivo: str) -> dict:
    """Cancela una reserva y libera el efectivo apartado.

    Args:
        reserva_id: Id de la reserva.
        motivo: Por qué se cancela.
    """
    r = _reserva_vigente(reserva_id)
    if isinstance(r, dict):
        return r
    if r.estado != "reservada":
        return {"error": f"No se puede cancelar una reserva en estado {r.estado}."}
    r.estado = "cancelada"
    ALMACEN.tiendas[r.tienda_id].reservado_cop -= r.monto_cop
    return {"ok": True}


def evaluar_riesgo(persona_id: str, monto_cop: int, dispositivo: str, reserva_id: str) -> dict:
    """Aplica topes por nivel y la regla de pitufeo. Puede bloquear a la persona.

    Args:
        persona_id: Id de la persona.
        monto_cop: Monto del retiro en pesos.
        dispositivo: Identificador del canal o dispositivo (ej. número de WhatsApp).
        reserva_id: Reserva que se está evaluando.
    """
    p = ALMACEN.personas.get(persona_id)
    r = _reserva_vigente(reserva_id)
    if p is None or isinstance(r, dict):
        return {"error": "Persona o reserva inexistente."}
    if r.persona_id != persona_id or r.monto_cop != monto_cop:
        return {"decision": "bloquear", "motivo": "Los datos no coinciden con la reserva."}
    if p.estado_registro == "bloqueada":
        return {"decision": "bloquear", "motivo": "La cuenta está bloqueada."}
    if monto_cop > TOPE_PERSONA_COP.get(p.nivel, 0):
        return {"decision": "bloquear", "motivo": "El monto supera el tope de su nivel."}
    desde = ahora() - VENTANA_PITUFEO
    recientes = [x for x in ALMACEN.reservas.values()
                 if x.persona_id == persona_id and x.estado in ("pagada", "entregada")
                 and x.pagada_en and x.pagada_en >= desde]
    if len(recientes) >= MAX_RETIROS_EN_VENTANA:
        p.estado_registro = "bloqueada"
        ALMACEN.alertas.append({"id": _nuevo_id("ale"), "persona_id": persona_id, "tienda_id": r.tienda_id,
                                "regla": "pitufeo", "detalle": f"{len(recientes)} retiros en 60 min",
                                "creada_en": ahora().isoformat(), "estado": "abierta"})
        return {"decision": "bloquear", "motivo": "Demasiados retiros en poco tiempo; la cuenta queda en revisión."}
    r.riesgo_ok = True
    return {"decision": "permitir", "motivo": "ok"}


def marcar_face_match(reserva_id: str, aprobado: bool, session_id: str) -> dict:
    """INTERNA (webhook de Didit): registra el resultado del face match en la reserva."""
    r = _reserva_vigente(reserva_id)
    if isinstance(r, dict):
        return r
    s = ALMACEN.sesiones_faciales.get(session_id)
    if s is None or s["reserva_id"] != reserva_id:
        return {"error": "La sesión no corresponde a la reserva."}
    s["aprobada"], s["score"] = aprobado, 0.97 if aprobado else 0.12
    r.face_match_ok = aprobado
    return {"ok": True}


def confirmar_entrega(reserva_id: str, codigo: str) -> dict:
    """El tendero confirma la entrega de los billetes con el código de 4 dígitos.

    Invariante 1: solo funciona si la reserva está pagada y el cobro completado.

    Args:
        reserva_id: Id de la reserva.
        codigo: Código de 4 dígitos que muestra la persona.
    """
    r = _reserva_vigente(reserva_id)
    if isinstance(r, dict):
        return r
    if r.estado != "pagada":
        return {"error": f"No se puede entregar: la reserva está {r.estado}, no pagada."}
    cobro = ALMACEN.cobros.get(r.incoming_payment_url or "")
    if not cobro or not cobro["completado"]:
        return {"error": "No se puede entregar: el cobro de la tienda no figura completado."}
    if codigo != r.codigo:
        return {"error": "El código no coincide."}
    r.estado = "entregada"
    r.entregado_en = ahora()
    t = ALMACEN.tiendas[r.tienda_id]
    t.reservado_cop -= r.monto_cop
    t.publicado_cop -= r.monto_cop
    return {"estado": "entregada"}


# -------------------------------------------------------------------- mcp-pagos

def resolver_wallet(wallet_address: str) -> dict:
    """Resuelve una wallet address de Open Payments.

    Args:
        wallet_address: Dirección tipo $ilp.interledger-test.dev/nombre.
    """
    if wallet_address not in WALLETS:
        return {"error": "No se encontró esa billetera."}
    asset_code, asset_scale = WALLETS[wallet_address]
    base = wallet_address.replace("$", "https://")
    return {"auth_server": "https://auth.interledger-test.dev", "resource_server": base,
            "asset_code": asset_code, "asset_scale": asset_scale}


def crear_cobro(wallet_tienda: str, monto_cop: int, reserva_id: str) -> dict:
    """Crea el incoming payment en la billetera de la tienda por el monto en COP.

    Args:
        wallet_tienda: Wallet address de la tienda.
        monto_cop: Monto en pesos que recibirá la tienda.
        reserva_id: Reserva asociada.
    """
    r = _reserva_vigente(reserva_id)
    if isinstance(r, dict):
        return r
    t = ALMACEN.tiendas[r.tienda_id]
    if wallet_tienda != t.wallet_address or monto_cop != r.monto_cop:
        return {"error": "La billetera o el monto no coinciden con la reserva."}
    url = f"{wallet_tienda.replace('$', 'https://')}/incoming-payments/{secrets.token_hex(6)}"
    ALMACEN.cobros[url] = {"reserva_id": reserva_id, "monto_cop": monto_cop, "recibido_cop": 0, "completado": False}
    r.incoming_payment_url = url
    return {"incoming_payment_url": url}


def cotizar(wallet_cliente: str, incoming_payment_url: str) -> dict:
    """Crea la quote: cuánto se debita de la billetera del cliente, comisión incluida.

    Args:
        wallet_cliente: Wallet address de quien paga.
        incoming_payment_url: Cobro creado con crear_cobro.
    """
    cobro = ALMACEN.cobros.get(incoming_payment_url)
    if cobro is None or wallet_cliente not in WALLETS:
        return {"error": "Cobro o billetera inexistente."}
    moneda, _ = WALLETS[wallet_cliente]
    comision_cop = COMISION_FIJA_COP + round(cobro["monto_cop"] * COMISION_PORCENTAJE)
    total_cop = cobro["monto_cop"] + comision_cop
    if moneda == "COP":
        debito, comision = total_cop, comision_cop
    elif moneda == "USD":
        debito, comision = round(total_cop / COP_POR_USD, 2), round(comision_cop / COP_POR_USD, 2)
    else:
        return {"error": f"Moneda {moneda} no soportada en la simulación."}
    quote_url = f"{wallet_cliente.replace('$', 'https://')}/quotes/{secrets.token_hex(6)}"
    vence = ahora() + VIGENCIA_QUOTE
    ALMACEN.quotes[quote_url] = {"wallet_cliente": wallet_cliente, "incoming_payment_url": incoming_payment_url,
                                 "debito": debito, "moneda": moneda, "vence_en": vence}
    ALMACEN.reservas[cobro["reserva_id"]].quote_url = quote_url
    return {"quote_url": quote_url, "debito": debito, "comision": comision, "moneda": moneda,
            "vence_en": vence.isoformat()}


def pedir_permiso(wallet_cliente: str, quote_url: str, reserva_id: str) -> dict:
    """Pide el grant interactivo de outgoing payment con tope igual al débito de la quote.

    Devuelve el link que la persona debe abrir para aprobar el pago en su billetera.

    Args:
        wallet_cliente: Wallet address de quien paga.
        quote_url: Quote creada con cotizar.
        reserva_id: Reserva asociada.
    """
    q = ALMACEN.quotes.get(quote_url)
    r = _reserva_vigente(reserva_id)
    if q is None or isinstance(r, dict) or r.quote_url != quote_url or q["wallet_cliente"] != wallet_cliente:
        return {"error": "La quote no corresponde a la reserva o a la billetera."}
    interact_ref = secrets.token_hex(6)
    ALMACEN.permisos[reserva_id] = {"limite_debito": q["debito"], "interact_ref": interact_ref, "aprobado": False}
    base = get_settings().public_base_url
    return {"redirect_url": f"{base}/simulador/billetera?reserva_id={reserva_id}&interact_ref={interact_ref}",
            "continue_uri": f"https://auth.interledger-test.dev/continue/{reserva_id}"}


def continuar_permiso(reserva_id: str, interact_ref: str) -> dict:
    """INTERNA (gateway /op/finish): continúa el grant tras la aprobación del usuario."""
    permiso = ALMACEN.permisos.get(reserva_id)
    if permiso is None or permiso["interact_ref"] != interact_ref:
        return {"error": "interact_ref inválido."}
    permiso["aprobado"] = True
    ALMACEN.reservas[reserva_id].grant_aprobado = True
    return {"ok": True}


def pagar(reserva_id: str) -> dict:
    """Ejecuta el outgoing payment con la quote aprobada.

    Invariantes 2, 3 y 4: exige face match aprobado, riesgo permitido y grant con tope.

    Args:
        reserva_id: Id de la reserva.
    """
    r = _reserva_vigente(reserva_id)
    if isinstance(r, dict):
        return r
    if r.estado != "reservada":
        return {"error": f"No se puede pagar una reserva en estado {r.estado}."}
    if r.face_match_ok is not True:
        return {"error": "No se paga sin verificación facial aprobada."}
    if r.riesgo_ok is not True:
        return {"error": "No se paga sin visto bueno de riesgo."}
    permiso = ALMACEN.permisos.get(reserva_id)
    if not permiso or not permiso["aprobado"]:
        return {"error": "La persona todavía no ha aprobado el pago en su billetera."}
    q = ALMACEN.quotes.get(r.quote_url or "")
    if q is None or ahora() > q["vence_en"]:
        return {"error": "La cotización venció; hay que cotizar de nuevo."}
    if q["debito"] > permiso["limite_debito"]:
        return {"error": "El débito supera el tope aprobado."}
    cobro = ALMACEN.cobros[q["incoming_payment_url"]]
    cobro["recibido_cop"], cobro["completado"] = cobro["monto_cop"], True
    r.outgoing_payment_id = _nuevo_id("out")
    r.estado, r.pagada_en = "pagada", ahora()
    return {"outgoing_payment_id": r.outgoing_payment_id, "estado": "completado"}


def estado_cobro(incoming_payment_url: str) -> dict:
    """Consulta si el cobro de la tienda ya quedó completado.

    Args:
        incoming_payment_url: Cobro creado con crear_cobro.
    """
    cobro = ALMACEN.cobros.get(incoming_payment_url)
    if cobro is None:
        return {"error": "No existe ese cobro."}
    return {"completado": cobro["completado"], "recibido": cobro["recibido_cop"]}
