# 03 · Reglas de oro

Herramienta: Claude Code (Claude Opus 5.5). Fecha: 2026-10-16.

## Prompts (textuales)

> haz commit atomicos, pero no los subas

> bien, comencemos a probar, enciende el local

> bien, va bien hay reglas de oro:
>
> 1. el agente debe hablar con ambas partes, está claro?
> 2. se debe solicitar en primera instancia siempre, la verificación de identidad con didit
> 3. cuando se haga entrega de dinero hacer una confirmación por ambas partes tambien
> 4. las comisiones deben ser basadas en la cantidad de dinero que el tendero tiene, es decir auto-calculable
> 5. el pago se aprueba cuando el usuario diga aprobar en el chat y ese registro guardarlo en base, para evitar problemas, tambien, para hacer la verificación de identidad, debemos hacer las politicas para que el usuario las acepte si no las acepta no podrá continuar operando

Respuestas a las preguntas de diseño que hizo Claude:

> Comisión: Por liquidez (Recomendado)
>
> ¿Quién recibe la comisión?: nosotros siempre un 1% de cada transacción
>
> Aprobación: Cupo + aprobar en chat (Recomendado)
>
> Didit: Usuario en cada retiro (Recomendado)

## Resultado

- Políticas (`/politicas`), aceptación guardada y obligatoria antes de verificar identidad.
- Didit al inicio de cada retiro; sin verificación vigente no se reserva.
- Comisión del tendero por liquidez + 1% de Caja de Barrio, con dos cobros separados.
- Cupo de Open Payments aprobado una vez; cada pago se aprueba escribiendo APROBAR (registrado).
- El agente habla con el tendero (`avisar_contraparte`) y la entrega exige confirmación de ambos.
- Al probar se encontró que el agente le dictaba el código de retiro al tendero; se bloqueó en código.
- Chat de pruebas con dos paneles (cliente y tendero).
