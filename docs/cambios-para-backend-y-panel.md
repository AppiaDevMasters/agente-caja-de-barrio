# Cambios de las reglas de oro que tocan la base y el panel

El agente ya funciona con estas reglas en modo simulado (`agente/herramientas/simuladas.py` es la
referencia de comportamiento). Para que los MCP reales y el panel las soporten, la base necesita esto.

## Reglas de oro

1. El agente habla con **ambas partes**: la persona que retira y el tendero, cada uno por su WhatsApp.
2. Toda operación empieza con la **verificación de identidad en Didit** (vigente 30 minutos).
3. La entrega se cierra con **confirmación de ambas partes**: tendero (con el código) y persona ("recibí").
4. **Comisiones auto-calculadas**: tendero = 1% + 2% × (monto / efectivo libre de la tienda), mínimo 1.000
   COP. Caja de Barrio cobra siempre el **1%** de cada transacción (cobro aparte a la billetera de la app).
5. El pago se aprueba cuando la persona **escribe APROBAR en el chat** y queda guardado. En Open Payments
   la persona aprueba **una sola vez** un cupo (grant con `limits.debitAmount` + `interval` P7D). Sin
   **aceptar las políticas** no se puede operar.

## Cambios en tablas compartidas

| Tabla | Cambio |
| --- | --- |
| `tiendas` | + `whatsapp_tendero`, `nombre_tendero` |
| `personas` | + `verificacion_session_id`, `verificado_hasta` |
| `reservas` | + `comision_tendero_cop`, `comision_plataforma_cop`, `verificacion_session_id`, `aprobacion_en`, `entrega_tendero_en`, `recibido_cliente_en`; estado nuevo `en_disputa` |
| `retiros` | + `cobro_plataforma_url` (incoming payment del 1% en la billetera de la app) |
| `alertas` | reglas nuevas: `verificacion_facial_fallida`, `entrega_no_recibida` |

## Tablas nuevas (registros de auditoría, solo inserción)

| Tabla | Campos |
| --- | --- |
| `aceptaciones_politicas` | `id`, `whatsapp`, `version` (hoy `v1-2026-10`), `texto_usuario`, `aceptada_en` |
| `aprobaciones_pago` | `id`, `reserva_id`, `persona_id`, `quote_url`, `debito`, `moneda`, `texto_usuario`, `canal`, `aprobada_en` |
| `confirmaciones_entrega` | `id`, `reserva_id`, `parte` (tendero o cliente), `recibido`, `texto_usuario`, `confirmada_en` |
| `cupos` (de mcp-pagos) | `persona_id`, `grant_id`, `limite`, `moneda`, `intervalo`, `usado`, `aprobado_en`; el access token cifrado solo lo guarda mcp-pagos |

## Herramientas MCP que cambian

| Servidor | Herramienta | Cambio |
| --- | --- | --- |
| mcp-identidad | `consultar_persona` | Devuelve `rol` (cliente, tendero, no_registrada), `politicas_aceptadas`, `verificacion_vigente`, `cupo_aprobado` |
| mcp-identidad | `aceptar_politicas` | Nueva, interna |
| mcp-identidad | `registrar_persona` | Nueva |
| mcp-identidad | `crear_sesion_facial` | Ya no pide `reserva_id`: se hace antes de reservar |
| mcp-identidad | `marcar_face_match(session_id, aprobado)` | Pasa de mcp-caja a mcp-identidad; deja la identidad vigente 30 min |
| mcp-mapa | `buscar_cajas_cercanas` | Devuelve las comisiones de cada tienda |
| mcp-caja | `reservar_efectivo` | Exige políticas e identidad vigente; calcula y guarda comisiones |
| mcp-caja | `reservas_de_tienda` | Nueva (para el tendero) |
| mcp-caja | `confirmar_entrega` | Lado del tendero; no cierra sola |
| mcp-caja | `confirmar_recibido` | Nueva, interna; lado de la persona; si dice que no, `en_disputa` |
| mcp-pagos | `pedir_cupo` / `continuar_permiso(grant_id, interact_ref)` | Reemplazan `pedir_permiso` por reserva |
| mcp-pagos | `crear_cobro` | Crea dos incoming payments: tienda (monto + comisión) y app (1%) |
| mcp-pagos | `registrar_aprobacion` | Nueva, interna |
| mcp-pagos | `pagar` | Exige aprobación registrada y cupo disponible |

## Para el panel

- Ver por retiro: comisión del tendero, 1% de Caja de Barrio, aprobación (texto y hora) y las dos confirmaciones de entrega.
- Cola de disputas (`en_disputa`) y alertas de verificación fallida.
- Versión de políticas aceptada por persona.

## Túnel

Lo levanta quien corra el compose y apunta al agente. Su URL pública va en `PUBLIC_BASE_URL` (agente),
`OP_FINISH_URL` (mcp-pagos, `<url>/op/finish`) y en los webhooks de Meta y Didit.
