"""Herramientas simuladas en memoria.

Replican nombre, entradas y salidas de las herramientas de los servidores MCP
(mcp-pagos, mcp-mapa, mcp-caja, mcp-identidad) para poder probar el agente sin
que esos servidores existan todavía. Las invariantes de seguridad y las reglas
de oro se validan aquí en código, igual que deberán hacerlo los MCP reales:

1. El agente habla con ambas partes: cada tienda tiene el WhatsApp de su tendero.
2. Toda operación empieza con la verificación de identidad en Didit.
3. La entrega se confirma por ambas partes (tendero y persona).
4. La comisión del tendero se calcula sola según su efectivo libre; Caja de Barrio cobra 1%.
5. El pago se aprueba escribiendo "aprobar" en el chat y queda registrado; sin aceptar
   las políticas no se puede operar.

Las herramientas nunca lanzan excepciones al modelo: devuelven {"error": ...}
para que el agente le explique a la persona qué pasó.
"""

from __future__ import annotations

import json
import math
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from agente.config import get_settings

POLITICAS_VERSION = "v1-2026-10"

VIGENCIA_RESERVA = timedelta(minutes=15)
VIGENCIA_QUOTE = timedelta(minutes=10)
VIGENCIA_VERIFICACION = timedelta(minutes=30)
VENTANA_PITUFEO = timedelta(minutes=60)
MAX_RETIROS_EN_VENTANA = 3

TOPE_TIENDA_COP = {"basico": 300_000, "comercio": 1_000_000, "aliado": 3_000_000}
TOPE_PERSONA_COP = {1: 500_000, 2: 2_000_000}

# Regla 4: la comisión del tendero sube cuando el retiro se lleva gran parte de su efectivo libre.
COMISION_TENDERO_BASE = 0.01
COMISION_TENDERO_EXTRA = 0.02
COMISION_TENDERO_MINIMA_COP = 1_000
COMISION_PLATAFORMA = 0.01

# Tasa fija para simular la conversión de la remesa.
COP_POR_USD = 4_000

# Cupo que la persona aprueba una sola vez en su billetera (grant con tope e intervalo).
CUPO_POR_MONEDA = {"COP": 1_000_000, "USD": 300}

# Billetera virtual: el ASE lleva el saldo de cada wallet. Con esto nace una persona en la demo.
SALDO_INICIAL_DEMO = {"COP": 1_000_000, "USD": 300}
BASE_WALLETS = "$ilp.interledger-test.dev"
INTERVALO_CUPO = "P7D"

WALLET_TIENDA = "$ilp.interledger-test.dev/tienda-cajadebarrio"
WALLET_APP = "$ilp.interledger-test.dev/app-cajadebarrio"
WALLET_APP_COP = "$ilp.interledger-test.dev/app-cajadebarrio-cop"
WALLETS = {
    "$ilp.interledger-test.dev/laura-cajadebarrio": ("COP", 2),
    "$ilp.interledger-test.dev/andres-cajadebarrio": ("USD", 2),
    WALLET_TIENDA: ("COP", 2),
    WALLET_APP: ("EUR", 2),
    WALLET_APP_COP: ("COP", 2),
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
    verificacion_session: Optional[str] = None
    verificado_hasta: Optional[datetime] = None
    cupo: Optional[dict] = None  # {"limite", "moneda", "usado", "intervalo"}


@dataclass
class Tienda:
    id: str
    nombre: str
    direccion: str
    lat: float
    lon: float
    nivel: str
    whatsapp_tendero: str
    nombre_tendero: str
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
    comision_tendero_cop: int
    comision_plataforma_cop: int
    codigo: str
    creada_en: datetime
    vence_en: datetime
    verificacion_session: str
    estado: str = "reservada"
    riesgo_ok: bool = False
    face_match_ok: bool = False
    incoming_payment_url: Optional[str] = None
    cobro_plataforma_url: Optional[str] = None
    quote_url: Optional[str] = None
    aprobacion_en: Optional[datetime] = None
    outgoing_payment_id: Optional[str] = None
    pagada_en: Optional[datetime] = None
    entrega_tendero_en: Optional[datetime] = None
    recibido_cliente_en: Optional[datetime] = None
    entregado_en: Optional[datetime] = None

    @property
    def total_cop(self) -> int:
        return self.monto_cop + self.comision_tendero_cop + self.comision_plataforma_cop


@dataclass
class SolicitudTendero:
    id: str
    whatsapp: str
    nombre: str
    tipo_documento: str
    cedula: str
    nombre_tienda: str
    direccion: str
    lat: float
    lon: float
    wallet_address: str
    efectivo_estimado_cop: int
    creada_en: datetime
    estado: str = "verificando"  # verificando, en_revision, correccion_pedida, aprobada, rechazada
    verificacion_session: Optional[str] = None
    motivo: Optional[str] = None
    campos_a_corregir: list[str] = field(default_factory=list)
    nivel: Optional[str] = None
    tienda_id: Optional[str] = None
    historial: list[dict] = field(default_factory=list)


@dataclass
class Almacen:
    personas: dict[str, Persona] = field(default_factory=dict)
    tiendas: dict[str, Tienda] = field(default_factory=dict)
    reservas: dict[str, Reserva] = field(default_factory=dict)
    cobros: dict[str, dict] = field(default_factory=dict)
    quotes: dict[str, dict] = field(default_factory=dict)
    grants: dict[str, dict] = field(default_factory=dict)
    sesiones_faciales: dict[str, dict] = field(default_factory=dict)
    alertas: list[dict] = field(default_factory=list)
    # Billetera virtual: saldo por wallet (en su moneda) y movimientos (solo inserción).
    saldos: dict[str, float] = field(default_factory=dict)
    movimientos: list[dict] = field(default_factory=list)
    # Registros de auditoría que en la base real son tablas propias.
    solicitudes_tendero: dict[str, SolicitudTendero] = field(default_factory=dict)
    aceptaciones_politicas: list[dict] = field(default_factory=list)
    aprobaciones_pago: list[dict] = field(default_factory=list)
    confirmaciones_entrega: list[dict] = field(default_factory=list)


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
    # Tiendas semilla en Aranjuez, Medellín (cerca de Ruta N), cada una con su tendero.
    for t in [
        Tienda("tie_jaime", "Tienda Don Jaime", "Cra 50 #92-15", 6.27610, -75.55800, "comercio",
               "573000000010", "Don Jaime", publicado_cop=800_000),
        Tienda("tie_paisa", "Minimercado El Paisa", "Cra 51 #90-22", 6.27560, -75.55790, "comercio",
               "573000000011", "Don Ramiro", publicado_cop=600_000),
        Tienda("tie_gloria", "Tienda Doña Gloria", "Cl 93 #49-40", 6.28010, -75.55710, "basico",
               "573000000012", "Doña Gloria", publicado_cop=250_000),
        Tienda("tie_esperanza", "Granero La Esperanza", "Cl 95 #50-10", 6.28220, -75.55640, "aliado",
               "573000000013", "Doña Marta", publicado_cop=1_500_000),
        Tienda("tie_aranjuez", "Autoservicio Aranjuez", "Cra 49 #88-05", 6.27310, -75.55520, "basico",
               "573000000014", "Don Luis", publicado_cop=150_000),
    ]:
        ALMACEN.tiendas[t.id] = t
    for wallet, (moneda, _) in WALLETS.items():
        if wallet not in ALMACEN.saldos:
            _mover(wallet, SALDO_INICIAL_DEMO[moneda] if wallet in _WALLETS_CLIENTES else 0, "carga_inicial")


_WALLETS_CLIENTES = {"$ilp.interledger-test.dev/laura-cajadebarrio", "$ilp.interledger-test.dev/andres-cajadebarrio"}


def _mover(wallet: str, monto: float, tipo: str, reserva_id: Optional[str] = None) -> None:
    ALMACEN.saldos[wallet] = round(ALMACEN.saldos.get(wallet, 0) + monto, 2)
    ALMACEN.movimientos.append({"wallet_address": wallet, "tipo": tipo, "monto": monto, "reserva_id": reserva_id,
                                "saldo": ALMACEN.saldos[wallet], "en": ahora().isoformat()})


def _crear_wallet(nombre: str, moneda: str = "COP", saldo_inicial: float = 0) -> str:
    """Crea la wallet en nuestro ASE (en el backend real, con la Admin API de Rafiki)."""
    base = "".join(c if c.isalnum() else "-" for c in nombre.lower()).strip("-") or "persona"
    wallet = f"{BASE_WALLETS}/{base}"
    n = 2
    while wallet in WALLETS:
        wallet, n = f"{BASE_WALLETS}/{base}-{n}", n + 1
    WALLETS[wallet] = (moneda, 2)
    _mover(wallet, saldo_inicial, "carga_inicial")
    return wallet


reiniciar()


def _metros(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)))


def calcular_comisiones(monto_cop: int, libre_cop: int) -> dict:
    """Regla 4: comisión del tendero según qué parte de su efectivo libre se lleva el retiro."""
    proporcion = min(monto_cop / libre_cop, 1.0) if libre_cop > 0 else 1.0
    tasa = COMISION_TENDERO_BASE + COMISION_TENDERO_EXTRA * proporcion
    tendero = max(COMISION_TENDERO_MINIMA_COP, round(monto_cop * tasa))
    plataforma = round(monto_cop * COMISION_PLATAFORMA)
    return {"comision_tendero_cop": tendero, "tasa_tendero": round(tasa, 4),
            "comision_plataforma_cop": plataforma, "total_cop": monto_cop + tendero + plataforma}


def _acepto_politicas(whatsapp: str) -> bool:
    return any(a["whatsapp"] == whatsapp and a["version"] == POLITICAS_VERSION
               for a in ALMACEN.aceptaciones_politicas)


def _verificacion_vigente(p: Persona) -> bool:
    return p.verificado_hasta is not None and ahora() <= p.verificado_hasta


def _tienda_de_tendero(whatsapp: str) -> Optional[Tienda]:
    return next((t for t in ALMACEN.tiendas.values() if t.whatsapp_tendero == whatsapp), None)


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
    """Identifica quién escribe: persona que retira, tendero o alguien no registrado.

    Args:
        whatsapp: Número de WhatsApp con indicativo, solo dígitos (ej. 573001234567).
    """
    tienda = _tienda_de_tendero(whatsapp)
    if tienda:
        return {"rol": "tendero", "tienda_id": tienda.id, "nombre_tienda": tienda.nombre,
                "nombre": tienda.nombre_tendero, "estado_tienda": tienda.estado,
                "efectivo_libre_cop": tienda.libre_cop, "wallet_address": tienda.wallet_address,
                "politicas_aceptadas": _acepto_politicas(whatsapp), "politicas_version": POLITICAS_VERSION}
    base = {"politicas_aceptadas": _acepto_politicas(whatsapp), "politicas_version": POLITICAS_VERSION}
    solicitud = _solicitud_abierta(whatsapp)
    if solicitud:
        base["solicitud_id"], base["estado_solicitud"] = solicitud.id, solicitud.estado
    for p in ALMACEN.personas.values():
        if p.whatsapp == whatsapp:
            cupo = p.cupo or {}
            return {**base, "rol": "cliente", "persona_id": p.id, "nombre": p.nombre,
                    "estado_registro": p.estado_registro, "nivel": p.nivel, "wallet_address": p.wallet_address,
                    "verificacion_vigente": _verificacion_vigente(p),
                    "cupo_aprobado": bool(cupo), "cupo_disponible": cupo.get("limite", 0) - cupo.get("usado", 0),
                    "cupo_moneda": cupo.get("moneda")}
    if solicitud:
        return {**base, "rol": "solicitante", "persona_id": None, "nombre": solicitud.nombre}
    return {**base, "rol": "no_registrada", "persona_id": None}


def aceptar_politicas(whatsapp: str, version: str, texto_usuario: str) -> dict:
    """INTERNA: guarda que la persona aceptó las políticas (lo llama el agente con su mensaje real)."""
    if version != POLITICAS_VERSION:
        return {"error": f"La versión vigente de las políticas es {POLITICAS_VERSION}."}
    if not _acepto_politicas(whatsapp):
        ALMACEN.aceptaciones_politicas.append({"whatsapp": whatsapp, "version": version,
                                               "texto_usuario": texto_usuario, "en": ahora().isoformat()})
    return {"ok": True, "version": version}


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


def registrar_persona(whatsapp: str, tipo: str, numero: str, wallet_address: str) -> dict:
    """Crea el registro de una persona nueva después de validar su cédula.

    Args:
        whatsapp: Número de WhatsApp de la persona.
        tipo: "CC" o "PPT".
        numero: Número del documento.
        wallet_address: Billetera de Open Payments desde la que pagará.
    """
    if not _acepto_politicas(whatsapp):
        return {"error": "Primero debe aceptar las políticas."}
    if any(p.whatsapp == whatsapp for p in ALMACEN.personas.values()):
        return {"error": "Ese número ya está registrado."}
    cedula = verificar_cedula(tipo, numero)
    if not cedula.get("valida"):
        return {"error": "El documento no es válido."}
    if wallet_address not in WALLETS:
        return {"error": "No se encontró esa billetera."}
    p = Persona(_nuevo_id("per"), whatsapp, cedula["nombre_completo"], numero, wallet_address,
                estado_registro="verificando")
    ALMACEN.personas[p.id] = p
    return {"persona_id": p.id, "estado_registro": p.estado_registro}


def crear_sesion_facial(persona_id: str = "", motivo: str = "retiro", solicitud_id: str = "",
                        whatsapp: str = "", tienda_id: str = "") -> dict:
    """Crea la sesión de Didit (documento + prueba de vida). Es el primer paso de toda operación.

    Formas:
    - Persona nueva (registro): whatsapp y motivo "alta". No se pide la cédula: Didit la lee del documento
      y el backend la valida con Verifik.
    - Tendero registrado en el panel: tienda_id y motivo "alta_tendero".
    - Cliente que va a retirar: persona_id y motivo "retiro".

    Args:
        persona_id: Id de la persona (clientes ya registrados).
        motivo: "alta", "retiro" o "alta_tendero".
        solicitud_id: Id de una solicitud de tendero hecha por WhatsApp (motivo "alta_tendero").
        whatsapp: WhatsApp de una persona nueva (motivo "alta").
        tienda_id: Id de la tienda registrada en el panel (motivo "alta_tendero").
    """
    base = get_settings().public_base_url
    if tienda_id:
        t = ALMACEN.tiendas.get(tienda_id)
        if t is None:
            return {"error": f"No existe la tienda {tienda_id}."}
        if not _acepto_politicas(t.whatsapp_tendero):
            return {"error": "Sin aceptar las políticas no se puede verificar la identidad."}
        if t.estado != "pendiente_verificacion":
            return {"error": f"La tienda está {t.estado}; no necesita verificación."}
        session_id = _nuevo_id("did")
        ALMACEN.sesiones_faciales[session_id] = {"persona_id": None, "tienda_id": tienda_id,
                                                 "motivo": "alta_tendero", "aprobada": None, "score": None}
        return {"session_id": session_id, "url_verificacion": f"{base}/simulador/didit?session_id={session_id}"}
    if whatsapp and not persona_id:
        if not _acepto_politicas(whatsapp):
            return {"error": "Sin aceptar las políticas no se puede verificar la identidad."}
        existente = next((x for x in ALMACEN.personas.values() if x.whatsapp == whatsapp), None)
        if existente is None:
            existente = Persona(_nuevo_id("per"), whatsapp, "", "", "", estado_registro="verificando")
            ALMACEN.personas[existente.id] = existente
        persona_id, motivo = existente.id, ("alta" if existente.estado_registro != "aprobada" else motivo)
    if solicitud_id:
        sol = ALMACEN.solicitudes_tendero.get(solicitud_id)
        if sol is None:
            return {"error": f"No existe la solicitud {solicitud_id}."}
        if not _acepto_politicas(sol.whatsapp):
            return {"error": "Sin aceptar las políticas no se puede verificar la identidad."}
        if sol.estado != "verificando":
            return {"error": f"La solicitud está {sol.estado}; no necesita verificación."}
        session_id = _nuevo_id("did")
        ALMACEN.sesiones_faciales[session_id] = {"persona_id": None, "solicitud_id": solicitud_id,
                                                 "motivo": "alta_tendero", "aprobada": None, "score": None}
        return {"session_id": session_id, "url_verificacion": f"{base}/simulador/didit?session_id={session_id}"}
    p = ALMACEN.personas.get(persona_id)
    if p is None:
        return {"error": f"No existe la persona {persona_id}."}
    if not _acepto_politicas(p.whatsapp):
        return {"error": "Sin aceptar las políticas no se puede verificar la identidad."}
    if p.estado_registro in ("bloqueada", "rechazada"):
        return {"error": f"La persona no puede operar (estado {p.estado_registro})."}
    session_id = _nuevo_id("did")
    ALMACEN.sesiones_faciales[session_id] = {"persona_id": persona_id, "motivo": motivo,
                                             "aprobada": None, "score": None}
    return {"session_id": session_id, "url_verificacion": f"{base}/simulador/didit?session_id={session_id}"}


def estado_verificacion(session_id: str) -> dict:
    """Consulta el resultado de una sesión de Didit. Úsala cuando la persona diga que ya terminó (LISTO).

    Si Didit ya decidió y el resultado todavía no se había procesado (porque no llegó webhook), lo
    procesa aquí igual que el webhook: Verifik, registro, billetera o tienda activa.

    Args:
        session_id: Id de la sesión devuelto por crear_sesion_facial.
    """
    s = ALMACEN.sesiones_faciales.get(session_id)
    if s is None:
        return {"error": f"No existe la sesión {session_id}."}
    if s["aprobada"] is None and s.get("decision_didit") is not None:
        # En el backend real: GET a la API de Didit con la decisión de la sesión.
        marcar_face_match(session_id, s["decision_didit"])
    quien = (ALMACEN.tiendas[s["tienda_id"]].whatsapp_tendero if s.get("tienda_id")
             else ALMACEN.solicitudes_tendero[s["solicitud_id"]].whatsapp if s.get("solicitud_id")
             else ALMACEN.personas[s["persona_id"]].whatsapp)
    return {"aprobada": s["aprobada"], "score": s["score"], "pendiente": s["aprobada"] is None,
            "motivo": s["motivo"], "whatsapp": quien, "persona_id": s.get("persona_id"),
            "tienda_id": s.get("tienda_id")}


def registrar_decision_didit(session_id: str, aprobado: bool) -> dict:
    """SIMULADOR: Didit decidió, pero sin webhook. Queda pendiente hasta que alguien consulte el estado."""
    s = ALMACEN.sesiones_faciales.get(session_id)
    if s is None:
        return {"error": f"No existe la sesión {session_id}."}
    s["decision_didit"] = aprobado
    return {"ok": True}


def marcar_face_match(session_id: str, aprobado: bool) -> dict:
    """INTERNA (webhook de Didit): registra el resultado y deja la identidad vigente 30 minutos."""
    s = ALMACEN.sesiones_faciales.get(session_id)
    if s is None:
        return {"error": f"No existe la sesión {session_id}."}
    s["aprobada"], s["score"] = aprobado, 0.97 if aprobado else 0.12
    if s.get("solicitud_id"):
        sol = ALMACEN.solicitudes_tendero[s["solicitud_id"]]
        sol.verificacion_session = session_id
        sol.estado = "en_revision" if aprobado else "rechazada"
        if not aprobado:
            sol.motivo = "La verificación de identidad no fue aprobada."
        _historial(sol, "didit", "verificacion_identidad", "aprobada" if aprobado else "rechazada")
        return {"ok": True, "whatsapp": sol.whatsapp, "persona_id": None, "solicitud_id": sol.id,
                "motivo": "alta_tendero", "estado_solicitud": sol.estado}
    if s.get("tienda_id"):
        t = ALMACEN.tiendas[s["tienda_id"]]
        if aprobado:
            documento = _documento_leido_por_didit(session_id)
            valida = verificar_cedula("CC", documento["numero"]).get("valida")
            t.estado = "activa" if valida else "revision_manual"
        else:
            ALMACEN.alertas.append({"id": _nuevo_id("ale"), "persona_id": None, "tienda_id": t.id,
                                    "regla": "verificacion_facial_fallida", "detalle": f"sesión {session_id}",
                                    "creada_en": ahora().isoformat(), "estado": "abierta"})
        return {"ok": True, "whatsapp": t.whatsapp_tendero, "persona_id": None, "tienda_id": t.id,
                "motivo": "alta_tendero", "estado_tienda": t.estado}
    p = ALMACEN.personas[s["persona_id"]]
    if aprobado:
        p.verificacion_session, p.verificado_hasta = session_id, ahora() + VIGENCIA_VERIFICACION
        if s["motivo"] == "alta":
            # Didit leyó el documento; Verifik confirma la cédula. Si no coincide, revisión manual.
            documento = _documento_leido_por_didit(session_id)
            if verificar_cedula("CC", documento["numero"]).get("valida"):
                p.cedula, p.nombre = documento["numero"], p.nombre or documento["nombre"]
                p.estado_registro = "aprobada"
                if not p.wallet_address:
                    p.wallet_address = _crear_wallet(p.nombre, "COP", SALDO_INICIAL_DEMO["COP"])
            else:
                p.estado_registro = "revision_manual"
    else:
        p.verificacion_session, p.verificado_hasta = None, None
        ALMACEN.alertas.append({"id": _nuevo_id("ale"), "persona_id": p.id, "tienda_id": None,
                                "regla": "verificacion_facial_fallida", "detalle": f"sesión {session_id}",
                                "creada_en": ahora().isoformat(), "estado": "abierta"})
    return {"ok": True, "whatsapp": p.whatsapp, "persona_id": p.id, "motivo": s["motivo"]}


def _documento_leido_por_didit(session_id: str) -> dict:
    """En el real, el backend lo toma de la decisión de Didit; aquí, uno fijo por sesión."""
    s = ALMACEN.sesiones_faciales[session_id]
    if "documento" not in s:
        s["documento"] = {"numero": str(1_000_000_000 + secrets.randbelow(99_999_999)), "nombre": "Persona Verificada"}
    return s["documento"]


def procesar_webhook_didit(cuerpo: str, firma: str) -> dict:
    """INTERNA (gateway /webhook/didit): interpreta el webhook de Didit y registra el resultado.

    El backend real valida `firma` (X-Signature-V2) con DIDIT_WEBHOOK_SECRET; la simulación no firma.
    """
    try:
        datos = json.loads(cuerpo)
    except ValueError:
        return {"error": "El webhook de Didit no es JSON válido."}
    estado = datos.get("status")
    if estado not in ("Approved", "Declined"):
        return {"procesado": False, "ignorado": estado}
    session_id = datos.get("vendor_data") or datos.get("session_id", "")
    r = marcar_face_match(session_id, estado == "Approved")
    if "error" in r:
        return r
    return {"procesado": True, "session_id": session_id, "aprobado": estado == "Approved", **r}


# ------------------------------------------------- solicitudes de tendero

_ESTADOS_ABIERTOS = ("verificando", "en_revision", "correccion_pedida")


def _solicitud_abierta(whatsapp: str) -> Optional[SolicitudTendero]:
    abiertas = [x for x in ALMACEN.solicitudes_tendero.values()
                if x.whatsapp == whatsapp and x.estado in _ESTADOS_ABIERTOS]
    return max(abiertas, key=lambda x: x.creada_en) if abiertas else None


def _historial(sol: SolicitudTendero, actor: str, accion: str, detalle: Optional[str] = None) -> None:
    sol.historial.append({"ts": ahora().isoformat(), "actor": actor, "accion": accion, "detalle": detalle})


def _checks(sol: SolicitudTendero) -> list[dict]:
    """Señales para que el panel decida. No bloquean la solicitud: solo se muestran."""
    cedula = verificar_cedula(sol.tipo_documento, sol.cedula)
    moneda = WALLETS.get(sol.wallet_address, (None, None))[0]
    sesion = ALMACEN.sesiones_faciales.get(sol.verificacion_session or "", {})
    duplicados = []
    if any(p.whatsapp == sol.whatsapp for p in ALMACEN.personas.values()):
        duplicados.append("el WhatsApp ya es de un cliente")
    duplicados += [f"la wallet ya está en {t.nombre}" for t in ALMACEN.tiendas.values()
                   if t.wallet_address == sol.wallet_address]

    def check(clave, ok, detalle_ok, detalle_mal, nivel_mal="error"):
        return {"clave": clave, "estado": "ok" if ok else nivel_mal, "detalle": detalle_ok if ok else detalle_mal}

    pendiente = sesion.get("aprobada") is None
    return [
        check("cedula_valida", cedula.get("valida"), "Verifik: documento válido", "Verifik: documento inválido"),
        check("face_match", sesion.get("aprobada") is True, f"Didit {sesion.get('score')}",
              "Didit: pendiente" if pendiente else "Didit: rechazada", "alerta" if pendiente else "error"),
        check("wallet_resuelve", moneda == "COP", "COP, escala 2",
              "La wallet no resuelve" if moneda is None else f"La wallet es {moneda}, no COP"),
        check("duplicados", not duplicados, "Sin coincidencias", "; ".join(duplicados), "alerta"),
        check("politicas", _acepto_politicas(sol.whatsapp), POLITICAS_VERSION, "No aceptó las políticas vigentes"),
    ]


def solicitar_ser_tendero(whatsapp: str, tipo: str, numero: str, nombre_tienda: str, direccion: str,
                          lat: float, lon: float, wallet_address: str, efectivo_estimado_cop: int) -> dict:
    """Crea la solicitud de alguien que quiere registrar su tienda como punto de retiro.

    Después hay que verificar su identidad con crear_sesion_facial(solicitud_id=..., motivo="alta_tendero").
    La solicitud queda en revisión del equipo de Caja de Barrio, que la aprueba o rechaza desde el panel.

    Args:
        whatsapp: Número de WhatsApp de quien solicita.
        tipo: "CC" o "PPT".
        numero: Número del documento.
        nombre_tienda: Nombre de la tienda.
        direccion: Dirección de la tienda.
        lat: Latitud de la tienda (del pin de ubicación).
        lon: Longitud de la tienda (del pin de ubicación).
        wallet_address: Billetera de Open Payments de la tienda (en pesos).
        efectivo_estimado_cop: Cuánto efectivo maneja la tienda al día, en pesos.
    """
    if not _acepto_politicas(whatsapp):
        return {"error": "Primero debe aceptar las políticas."}
    if _tienda_de_tendero(whatsapp):
        return {"error": "Ese número ya es tendero de una tienda activa."}
    abierta = _solicitud_abierta(whatsapp)
    if abierta:
        return {"error": f"Ya tiene una solicitud {abierta.estado} ({abierta.id})."}
    cedula = verificar_cedula(tipo, numero)
    if "error" in cedula:
        return cedula
    sol = SolicitudTendero(_nuevo_id("sol"), whatsapp, cedula.get("nombre_completo") or "SIN VALIDAR", tipo, numero,
                           nombre_tienda, direccion, lat, lon, wallet_address, efectivo_estimado_cop, ahora())
    ALMACEN.solicitudes_tendero[sol.id] = sol
    _historial(sol, "agente", "solicitud_creada")
    return {"solicitud_id": sol.id, "estado": sol.estado}


def consultar_solicitud_tendero(whatsapp: str) -> dict:
    """Estado de la solicitud de tienda de ese WhatsApp (la más reciente).

    Args:
        whatsapp: Número de WhatsApp de quien solicitó.
    """
    propias = [x for x in ALMACEN.solicitudes_tendero.values() if x.whatsapp == whatsapp]
    if not propias:
        return {"solicitud_id": None, "estado": None}
    sol = max(propias, key=lambda x: x.creada_en)
    return {"solicitud_id": sol.id, "estado": sol.estado, "nombre_tienda": sol.nombre_tienda,
            "motivo": sol.motivo, "campos_a_corregir": sol.campos_a_corregir, "tienda_id": sol.tienda_id}


def corregir_solicitud_tendero(solicitud_id: str, direccion: str = "", lat: Optional[float] = None,
                               lon: Optional[float] = None, wallet_address: str = "", tipo: str = "",
                               numero: str = "") -> dict:
    """Corrige los datos que el equipo pidió corregir; la solicitud vuelve a revisión.

    Args:
        solicitud_id: Id de la solicitud.
        direccion: Nueva dirección (si se pidió corregir la ubicación).
        lat: Nueva latitud.
        lon: Nueva longitud.
        wallet_address: Nueva billetera (si se pidió corregir la wallet).
        tipo: Nuevo tipo de documento (si se pidió corregir el documento).
        numero: Nuevo número de documento.
    """
    sol = ALMACEN.solicitudes_tendero.get(solicitud_id)
    if sol is None:
        return {"error": f"No existe la solicitud {solicitud_id}."}
    if sol.estado != "correccion_pedida":
        return {"error": f"La solicitud está {sol.estado}; no hay nada que corregir."}
    if direccion:
        sol.direccion = direccion
    if lat is not None and lon is not None:
        sol.lat, sol.lon = lat, lon
    if wallet_address:
        sol.wallet_address = wallet_address
    if tipo and numero:
        sol.tipo_documento, sol.cedula = tipo, numero
    sol.estado, sol.campos_a_corregir, sol.motivo = "en_revision", [], None
    _historial(sol, "agente", "solicitud_corregida")
    return {"solicitud_id": sol.id, "estado": sol.estado}


# --------------------------------------------- panel (lo expone /admin del backend)

AVISOS_SOLICITUD = {
    "aprobar": "Tu solicitud fue APROBADA: la tienda {tienda} quedó activa en nivel {nivel}. Ya puedes publicar tu "
               "efectivo del día.",
    "rechazar": "Tu solicitud para registrar la tienda {tienda} fue RECHAZADA. Motivo: {motivo}",
    "pedir_correccion": "Para seguir con tu solicitud de la tienda {tienda} necesitamos que corrijas: {campos}. "
                        "Motivo: {motivo}",
}


def listar_solicitudes(estado: str = "") -> dict:
    items = [detalle_solicitud(x.id) for x in sorted(ALMACEN.solicitudes_tendero.values(), key=lambda x: x.creada_en)
             if not estado or x.estado == estado]
    return {"items": items, "total": len(items)}


def detalle_solicitud(solicitud_id: str) -> dict:
    sol = ALMACEN.solicitudes_tendero.get(solicitud_id)
    if sol is None:
        return {"error": f"No existe la solicitud {solicitud_id}."}
    sesion = ALMACEN.sesiones_faciales.get(sol.verificacion_session or "", {})
    return {
        "id": sol.id, "estado": sol.estado, "creada_en": sol.creada_en.isoformat(),
        "solicitante": {"nombre": sol.nombre, "cedula": "****" + sol.cedula[-4:],
                        "whatsapp": "*******" + sol.whatsapp[-4:]},
        "tienda": {"nombre": sol.nombre_tienda, "direccion": sol.direccion, "lat": sol.lat, "lon": sol.lon,
                   "efectivo_estimado_cop": sol.efectivo_estimado_cop},
        "wallet": {"address": sol.wallet_address, "resuelve": sol.wallet_address in WALLETS,
                   "moneda": WALLETS.get(sol.wallet_address, (None,))[0]},
        "didit": {"liveness": {True: "aprobada", False: "rechazada"}.get(sesion.get("aprobada"), "pendiente"),
                  "score": sesion.get("score"), "session_id": sol.verificacion_session},
        "checks": _checks(sol), "motivo": sol.motivo, "campos_a_corregir": sol.campos_a_corregir,
        "tienda_id": sol.tienda_id, "historial": sol.historial,
    }


def decidir_solicitud(solicitud_id: str, decision: str, motivo: str, nivel: str = "basico",
                      campos: Optional[list[str]] = None, actor: str = "panel") -> dict:
    """Aprueba, rechaza o pide corrección. Devuelve a quién avisar y qué decirle."""
    sol = ALMACEN.solicitudes_tendero.get(solicitud_id)
    if sol is None:
        return {"error": f"No existe la solicitud {solicitud_id}."}
    if decision not in AVISOS_SOLICITUD:
        return {"error": "La decisión debe ser aprobar, rechazar o pedir_correccion."}
    if len(motivo.strip()) < 10:
        return {"error": "El motivo debe tener al menos 10 caracteres."}
    if sol.estado != "en_revision":
        return {"error": f"Solo se decide una solicitud en revisión (está {sol.estado})."}
    if decision == "aprobar":
        if nivel not in ("basico", "comercio"):
            return {"error": "El nivel debe ser basico o comercio (aliado requiere cuatro ojos)."}
        nombre_tendero = sol.nombre.split()[0].title() if sol.nombre else "Tendero"
        tienda = Tienda(_nuevo_id("tie"), sol.nombre_tienda, sol.direccion, sol.lat, sol.lon, nivel, sol.whatsapp,
                        nombre_tendero, sol.wallet_address)
        ALMACEN.tiendas[tienda.id] = tienda
        sol.estado, sol.nivel, sol.tienda_id = "aprobada", nivel, tienda.id
    elif decision == "rechazar":
        sol.estado, sol.motivo = "rechazada", motivo
    else:
        if not campos:
            return {"error": "Indica qué campos debe corregir."}
        sol.estado, sol.motivo, sol.campos_a_corregir = "correccion_pedida", motivo, list(campos)
    _historial(sol, actor, decision, motivo)
    aviso = AVISOS_SOLICITUD[decision].format(tienda=sol.nombre_tienda, nivel=nivel, motivo=motivo,
                                              campos=", ".join(campos or []))
    return {"ok": True, "estado": sol.estado, "tienda_id": sol.tienda_id, "whatsapp": sol.whatsapp, "aviso": aviso}


# --------------------------------------------------------------------- mcp-mapa

def buscar_cajas_cercanas(lat: float, lon: float, monto_cop: int, radio_m: int = 1500) -> dict:
    """Encuentra hasta 3 tiendas cercanas con efectivo libre suficiente, con su comisión calculada.

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
            candidatas.append({"id": t.id, "nombre": t.nombre, "direccion": t.direccion, "metros": m,
                               "lat": t.lat, "lon": t.lon, "wallet_address": t.wallet_address,
                               **calcular_comisiones(monto_cop, t.libre_cop)})
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
            "nivel": t.nivel, "wallet_address": t.wallet_address, "efectivo_libre_cop": t.libre_cop}


def publicar_efectivo(tienda_id: str, monto_cop: int) -> dict:
    """El tendero publica cuánto efectivo tiene disponible hoy.

    Args:
        tienda_id: Id de la tienda.
        monto_cop: Efectivo total disponible para retiros, en pesos.
    """
    t = ALMACEN.tiendas.get(tienda_id)
    if t is None:
        return {"error": f"No existe la tienda {tienda_id}."}
    if t.estado != "activa":
        return {"error": "La tienda todavía no está activa: el tendero debe verificar su identidad primero."}
    if monto_cop < t.reservado_cop:
        return {"error": "No puede publicar menos de lo que ya está reservado."}
    t.publicado_cop = monto_cop
    return {"ok": True, "libre_cop": t.libre_cop}


# --------------------------------------------------------------------- mcp-caja

def reservar_efectivo(tienda_id: str, persona_id: str, monto_cop: int) -> dict:
    """Aparta el efectivo en la tienda, calcula las comisiones y genera el código de 4 dígitos.

    Exige políticas aceptadas e identidad verificada en Didit hace menos de 30 minutos.

    Args:
        tienda_id: Id de la tienda elegida.
        persona_id: Id de la persona que retira.
        monto_cop: Monto en pesos (entero).
    """
    t = ALMACEN.tiendas.get(tienda_id)
    p = ALMACEN.personas.get(persona_id)
    if t is None or p is None:
        return {"error": "Tienda o persona inexistente."}
    if not _acepto_politicas(p.whatsapp):
        return {"error": "La persona no ha aceptado las políticas."}
    if p.estado_registro != "aprobada":
        return {"error": f"La persona no puede retirar (estado {p.estado_registro})."}
    if not _verificacion_vigente(p):
        return {"error": "Primero hay que verificar la identidad en Didit."}
    if t.estado != "activa":
        return {"error": "La tienda no está recibiendo retiros."}
    if monto_cop <= 0:
        return {"error": "El monto debe ser positivo."}
    if monto_cop > TOPE_TIENDA_COP[t.nivel]:
        return {"error": f"La tienda solo entrega hasta {TOPE_TIENDA_COP[t.nivel]} COP por retiro."}
    if t.libre_cop < monto_cop:
        return {"error": "La tienda ya no tiene ese efectivo libre."}
    comisiones = calcular_comisiones(monto_cop, t.libre_cop)
    t.reservado_cop += monto_cop
    r = Reserva(_nuevo_id("res"), tienda_id, persona_id, monto_cop, comisiones["comision_tendero_cop"],
                comisiones["comision_plataforma_cop"], f"{secrets.randbelow(10_000):04d}", ahora(),
                ahora() + VIGENCIA_RESERVA, p.verificacion_session, face_match_ok=True)
    ALMACEN.reservas[r.id] = r
    return {"reserva_id": r.id, "codigo_4_digitos": r.codigo, "vence_en": r.vence_en.isoformat(), **comisiones}


def consultar_reserva(reserva_id: str) -> dict:
    """Estado de una reserva, sus comisiones y qué pasos del retiro ya se completaron.

    Args:
        reserva_id: Id de la reserva.
    """
    r = _reserva_vigente(reserva_id)
    if isinstance(r, dict):
        return r
    t, p = ALMACEN.tiendas[r.tienda_id], ALMACEN.personas[r.persona_id]
    return {
        "reserva_id": r.id, "estado": r.estado, "tienda_id": r.tienda_id, "nombre_tienda": t.nombre,
        "persona_id": r.persona_id, "nombre_cliente": p.nombre,
        "whatsapp_cliente": p.whatsapp, "whatsapp_tendero": t.whatsapp_tendero,
        "monto_cop": r.monto_cop, "comision_tendero_cop": r.comision_tendero_cop,
        "comision_plataforma_cop": r.comision_plataforma_cop, "total_cop": r.total_cop,
        "vence_en": r.vence_en.isoformat(),
        "pasos": {"identidad_verificada": r.face_match_ok, "riesgo_ok": r.riesgo_ok,
                  "cobro_creado": r.incoming_payment_url is not None, "cotizado": r.quote_url is not None,
                  "aprobado_en_chat": r.aprobacion_en is not None,
                  "pagada": r.estado in ("pagada", "entregada"),
                  "entrega_confirmada_tendero": r.entrega_tendero_en is not None,
                  "recibido_confirmado_cliente": r.recibido_cliente_en is not None,
                  "entregada": r.estado == "entregada"},
    }


def reservas_de_tienda(tienda_id: str) -> dict:
    """Retiros activos de una tienda, para que el tendero sepa a quién espera.

    Args:
        tienda_id: Id de la tienda.
    """
    if tienda_id not in ALMACEN.tiendas:
        return {"error": f"No existe la tienda {tienda_id}."}
    activas = []
    for r in list(ALMACEN.reservas.values()):
        if r.tienda_id != tienda_id:
            continue
        r = _reserva_vigente(r.id)
        if r.estado in ("reservada", "pagada", "en_disputa"):
            activas.append({"reserva_id": r.id, "estado": r.estado, "monto_cop": r.monto_cop,
                            "comision_tendero_cop": r.comision_tendero_cop,
                            "cliente": ALMACEN.personas[r.persona_id].nombre.split()[0]})
    return {"reservas": activas}


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
    return {"ok": True, "motivo": motivo}


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


def _finalizar_si_ambos_confirmaron(r: Reserva) -> None:
    if r.entrega_tendero_en and r.recibido_cliente_en and r.estado == "pagada":
        r.estado, r.entregado_en = "entregada", ahora()
        t = ALMACEN.tiendas[r.tienda_id]
        t.reservado_cop -= r.monto_cop
        t.publicado_cop -= r.monto_cop


def confirmar_entrega(reserva_id: str, codigo: str) -> dict:
    """El TENDERO confirma que entregó los billetes, con el código de 4 dígitos de la persona.

    Invariante 1: solo funciona si la reserva está pagada y el cobro completado.
    La entrega queda cerrada cuando también la persona confirma que recibió.

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
    r.entrega_tendero_en = r.entrega_tendero_en or ahora()
    ALMACEN.confirmaciones_entrega.append({"reserva_id": r.id, "parte": "tendero", "en": ahora().isoformat()})
    _finalizar_si_ambos_confirmaron(r)
    return {"estado": r.estado, "falta_confirmacion_cliente": r.recibido_cliente_en is None}


def confirmar_recibido(reserva_id: str, recibido: bool, texto_usuario: str) -> dict:
    """INTERNA: la PERSONA confirma (o niega) que recibió los billetes. Si lo niega, se abre disputa."""
    r = _reserva_vigente(reserva_id)
    if isinstance(r, dict):
        return r
    if r.estado != "pagada":
        return {"error": f"La reserva está {r.estado}; no hay entrega pendiente por confirmar."}
    ALMACEN.confirmaciones_entrega.append({"reserva_id": r.id, "parte": "cliente", "recibido": recibido,
                                           "texto_usuario": texto_usuario, "en": ahora().isoformat()})
    if not recibido:
        r.estado = "en_disputa"
        ALMACEN.alertas.append({"id": _nuevo_id("ale"), "persona_id": r.persona_id, "tienda_id": r.tienda_id,
                                "regla": "entrega_no_recibida", "detalle": texto_usuario,
                                "creada_en": ahora().isoformat(), "estado": "abierta"})
        return {"estado": r.estado}
    r.recibido_cliente_en = r.recibido_cliente_en or ahora()
    _finalizar_si_ambos_confirmaron(r)
    return {"estado": r.estado, "falta_confirmacion_tendero": r.entrega_tendero_en is None}


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


def pedir_cupo(persona_id: str, wallet_cliente: str) -> dict:
    """Pide UNA vez el grant interactivo de outgoing payment con tope e intervalo (cupo semanal).

    Devuelve el link para que la persona apruebe el cupo en su billetera. Los retiros siguientes
    se aprueban en el chat y se pagan contra este cupo.

    Args:
        persona_id: Id de la persona.
        wallet_cliente: Wallet address desde la que pagará.
    """
    p = ALMACEN.personas.get(persona_id)
    if p is None or wallet_cliente != p.wallet_address:
        return {"error": "La billetera no corresponde a la persona."}
    moneda, _ = WALLETS[wallet_cliente]
    grant_id = _nuevo_id("gra")
    interact_ref = secrets.token_hex(6)
    ALMACEN.grants[grant_id] = {"persona_id": persona_id, "interact_ref": interact_ref,
                                "limite": CUPO_POR_MONEDA[moneda], "moneda": moneda, "aprobado": False}
    base = get_settings().public_base_url
    return {"redirect_url": f"{base}/simulador/billetera?grant_id={grant_id}&interact_ref={interact_ref}",
            "grant_id": grant_id, "limite": CUPO_POR_MONEDA[moneda], "moneda": moneda,
            "intervalo": INTERVALO_CUPO}


def continuar_permiso(grant_id: str, interact_ref: str, hash: str = "") -> dict:
    """INTERNA (gateway /op/finish): continúa el grant tras la aprobación en la billetera.

    El backend real verifica `hash`; la simulación no lo calcula.
    """
    g = ALMACEN.grants.get(grant_id)
    if g is None or g["interact_ref"] != interact_ref:
        return {"error": "interact_ref inválido."}
    g["aprobado"] = True
    p = ALMACEN.personas[g["persona_id"]]
    p.cupo = {"limite": g["limite"], "moneda": g["moneda"], "usado": 0, "intervalo": INTERVALO_CUPO}
    return {"ok": True, "whatsapp": p.whatsapp, "persona_id": p.id}


def crear_cobro(wallet_tienda: str, monto_cop: int, reserva_id: str) -> dict:
    """Crea los cobros del retiro: el de la tienda (retiro + su comisión) y el 1% de Caja de Barrio.

    Args:
        wallet_tienda: Wallet address de la tienda.
        monto_cop: Monto del retiro en pesos (sin comisiones; se suman solas).
        reserva_id: Reserva asociada.
    """
    r = _reserva_vigente(reserva_id)
    if isinstance(r, dict):
        return r
    t = ALMACEN.tiendas[r.tienda_id]
    if wallet_tienda != t.wallet_address or monto_cop != r.monto_cop:
        return {"error": "La billetera o el monto no coinciden con la reserva."}
    url = f"{wallet_tienda.replace('$', 'https://')}/incoming-payments/{secrets.token_hex(6)}"
    url_app = f"{WALLET_APP.replace('$', 'https://')}/incoming-payments/{secrets.token_hex(6)}"
    ALMACEN.cobros[url] = {"reserva_id": reserva_id, "monto_cop": r.monto_cop + r.comision_tendero_cop,
                           "recibido_cop": 0, "completado": False}
    ALMACEN.cobros[url_app] = {"reserva_id": reserva_id, "monto_cop": r.comision_plataforma_cop,
                               "recibido_cop": 0, "completado": False}
    r.incoming_payment_url, r.cobro_plataforma_url = url, url_app
    return {"incoming_payment_url": url, "cobro_plataforma_url": url_app,
            "tienda_recibe_cop": r.monto_cop + r.comision_tendero_cop,
            "caja_de_barrio_recibe_cop": r.comision_plataforma_cop}


def cotizar(wallet_cliente: str, incoming_payment_url: str, reserva_id: str = "") -> dict:
    """Cotiza cuánto se debita de la billetera de quien paga, con el desglose de comisiones.

    Args:
        wallet_cliente: Wallet address de quien paga.
        incoming_payment_url: Cobro de la tienda creado con crear_cobro.
        reserva_id: Reserva asociada (si se conoce).
    """
    cobro = ALMACEN.cobros.get(incoming_payment_url)
    if cobro is None or wallet_cliente not in WALLETS:
        return {"error": "Cobro o billetera inexistente."}
    r = ALMACEN.reservas[cobro["reserva_id"]]
    moneda, _ = WALLETS[wallet_cliente]
    if moneda == "COP":
        debito = r.total_cop
    elif moneda == "USD":
        debito = round(r.total_cop / COP_POR_USD, 2)
    else:
        return {"error": f"Moneda {moneda} no soportada en la simulación."}
    quote_url = f"{wallet_cliente.replace('$', 'https://')}/quotes/{secrets.token_hex(6)}"
    vence = ahora() + VIGENCIA_QUOTE
    ALMACEN.quotes[quote_url] = {"wallet_cliente": wallet_cliente, "reserva_id": r.id,
                                 "debito": debito, "moneda": moneda, "vence_en": vence}
    r.quote_url = quote_url
    return {"quote_url": quote_url, "debito": debito, "moneda": moneda, "vence_en": vence.isoformat(),
            "desglose_cop": {"retiro": r.monto_cop, "comision_tendero": r.comision_tendero_cop,
                             "comision_caja_de_barrio": r.comision_plataforma_cop, "total": r.total_cop}}


def registrar_aprobacion(reserva_id: str, persona_id: str, texto_usuario: str, canal: str) -> dict:
    """INTERNA: guarda en base la aprobación del pago que la persona escribió en el chat."""
    r = _reserva_vigente(reserva_id)
    if isinstance(r, dict):
        return r
    if r.persona_id != persona_id:
        return {"error": "La reserva no es de esta persona."}
    if r.estado != "reservada" or r.quote_url is None:
        return {"error": "No hay un pago cotizado pendiente de aprobación para esta reserva."}
    q = ALMACEN.quotes[r.quote_url]
    ALMACEN.aprobaciones_pago.append({"id": _nuevo_id("apr"), "reserva_id": r.id, "persona_id": persona_id,
                                      "quote_url": r.quote_url, "debito": q["debito"], "moneda": q["moneda"],
                                      "texto_usuario": texto_usuario, "canal": canal, "en": ahora().isoformat()})
    r.aprobacion_en = ahora()
    return {"ok": True, "debito": q["debito"], "moneda": q["moneda"]}


def pagar(reserva_id: str) -> dict:
    """Ejecuta los pagos (tienda y Caja de Barrio) contra el cupo aprobado.

    Exige: identidad verificada, riesgo permitido, aprobación escrita en el chat y cupo suficiente.

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
    if r.aprobacion_en is None:
        return {"error": "La persona todavía no ha escrito \"aprobar\" en el chat."}
    p = ALMACEN.personas[r.persona_id]
    q = ALMACEN.quotes.get(r.quote_url or "")
    if q is None or ahora() > q["vence_en"]:
        return {"error": "La cotización venció; hay que cotizar de nuevo."}
    if not p.cupo:
        return {"error": "La persona no ha aprobado su cupo en la billetera."}
    if p.cupo["usado"] + q["debito"] > p.cupo["limite"]:
        return {"error": "El pago supera el cupo disponible aprobado en la billetera."}
    if ALMACEN.saldos.get(p.wallet_address, 0) < q["debito"]:
        return {"error": "Saldo insuficiente en la billetera."}
    t = ALMACEN.tiendas[r.tienda_id]
    _mover(p.wallet_address, -q["debito"], "pago_retiro", r.id)
    _mover(t.wallet_address, r.monto_cop + r.comision_tendero_cop, "cobro_retiro", r.id)
    _mover(WALLET_APP_COP, r.comision_plataforma_cop, "comision_plataforma", r.id)
    for url in (r.incoming_payment_url, r.cobro_plataforma_url):
        cobro = ALMACEN.cobros[url]
        cobro["recibido_cop"], cobro["completado"] = cobro["monto_cop"], True
    p.cupo["usado"] += q["debito"]
    r.outgoing_payment_id = _nuevo_id("out")
    r.estado, r.pagada_en = "pagada", ahora()
    return {"outgoing_payment_id": r.outgoing_payment_id, "estado": "completado",
            "cupo_disponible": p.cupo["limite"] - p.cupo["usado"]}


def consultar_saldo(whatsapp: str) -> dict:
    """Billetera virtual: cuánto tiene la persona (o la tienda, si quien pregunta es tendero).

    Args:
        whatsapp: Número de WhatsApp de quien pregunta.
    """
    tienda = _tienda_de_tendero(whatsapp)
    persona = next((x for x in ALMACEN.personas.values() if x.whatsapp == whatsapp), None)
    wallet = tienda.wallet_address if tienda else (persona.wallet_address if persona else "")
    if not wallet:
        return {"error": "Esa persona todavía no tiene billetera: primero debe registrarse."}
    movimientos = [m for m in ALMACEN.movimientos if m["wallet_address"] == wallet][-5:]
    return {"wallet_address": wallet, "saldo": ALMACEN.saldos.get(wallet, 0), "moneda": WALLETS[wallet][0],
            "movimientos": movimientos}


def registrar_tendero_panel(nombre_tienda: str, direccion: str, lat: float, lon: float, nivel: str,
                            whatsapp_tendero: str, nombre_tendero: str, motivo: str) -> dict:
    """PANEL (POST /admin/tenderos): crea la tienda pendiente de verificación, con wallet y saldo en 0."""
    if len(motivo.strip()) < 10:
        return {"error": "El motivo debe tener al menos 10 caracteres."}
    if nivel not in TOPE_TIENDA_COP:
        return {"error": "El nivel debe ser basico, comercio o aliado."}
    if _tienda_de_tendero(whatsapp_tendero):
        return {"error": "Ese WhatsApp ya es tendero de otra tienda."}
    wallet = _crear_wallet(nombre_tienda, "COP", 0)
    t = Tienda(_nuevo_id("tie"), nombre_tienda, direccion, lat, lon, nivel, whatsapp_tendero, nombre_tendero,
               wallet, estado="pendiente_verificacion")
    ALMACEN.tiendas[t.id] = t
    aviso = (f"Caja de Barrio registró tu tienda {nombre_tienda}. Para activarla, escríbenos y verifica tu "
             f"identidad con Didit.")
    return {"tienda_id": t.id, "estado": t.estado, "wallet_address": wallet, "whatsapp": whatsapp_tendero,
            "aviso": aviso}


def estado_cobro(incoming_payment_url: str) -> dict:
    """Consulta si el cobro de la tienda ya quedó completado.

    Args:
        incoming_payment_url: Cobro creado con crear_cobro.
    """
    cobro = ALMACEN.cobros.get(incoming_payment_url)
    if cobro is None:
        return {"error": "No existe ese cobro."}
    return {"completado": cobro["completado"], "recibido": cobro["recibido_cop"]}
