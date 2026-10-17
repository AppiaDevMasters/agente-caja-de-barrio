# 07 · Prueba de punta a punta desde la UI de ADK

Herramienta: Claude Code (Claude Opus 5.5). Fecha: madrugada del 2026-10-17.

## Prompts (textuales)

> la prueba que vamos a hacer es a registrar a una persona cualquiera utilizando un token de open payment, ademas, hacer todo el proceso de punta a punta desde la ui de adk, entonces ahí es donde veremos que pasa, una persona abre la ui y otra tambien, por ejemplo yo sería el tendero, y mi compañero sería el que va a transferir, dime que falta?
>
> la prueba la haremos desde la ui de adk

Respuestas del equipo a las preguntas del agente:

> ¿Arranco ya con la parte del agente (UI de ADK en agente.cajadebarrio.lat, userId y avisos en la misma UI)? — si, arranca y haz un documento para el back y front para lograr eso y dejar la prueba lista
>
> ¿Con qué billetera paga tu compañero (quien transfiere)? — Se le crea al registrarse (Recomendado)
>
> ¿Cómo entras tú como tendero? — Pidiendo ser tendero (flujo real)

> la prueba consiste en:
>
> 1. registramos a un tendero desde el panel
> 2. registramos a una persona que es la que enviará la plata
> 3. hacemos todo el proceso de seguridad para ambos con didit
> 4. se hace verificacíon con verifik una vez didit ya bajó los datos del usuario
> 5. habrá como una wallet virtual que le mostrará al usuario cuanto tiene y al tendero tambien
>
> esa debe ser la prueba

> ya los puse es necesario el webhook? ya que estoy utilizando la cuenta de otro proyecto en sandbox, es necesario el webhook o con esas mismas puedo crear otro wehbook?

> hagamos esta primera prueba sin webhook, luego ya hacemos un pplan de implementación

> Sí, hagamos la prueba completa desde la UI de ADK: registro, Didit con LISTO y ver la billetera.

> cual es la clave?

> ya entré desde edge

> ya tenemos conectado open paymens? o esto sigue en test?

> perfecto, ya me sale 0, entonces como alguien mas abre una cuenta? para que me envie que soy el tendero

> el no será tendero, el será un usuario particular

> si, entonces el tiene que poner tambien las credenciales de admin verdad?

> ya se registró cristian, revisa, porque el será el particular que va a enviar el dinero

> revisa los logs que cristian intentó y ocurrio un problema

> pide la ubicación, pero como estamos desde adk, posiblemente no le de, entonces como hacemos¡

> dice que mi tienda se quedó sin efectivo porque? si ya publiqué que tengo 500.000 en efectivo

> ahora bien, que cumplimos y que nos falta para lograr el objetivo de un prueba e2e completa? hazme un documento completo en .md que cumplimos y que nos falta

> Sí, sube los 4 commits del agente y actualiza prompts/ y AI_USAGE.md del agente y del backend con los prompts de esta noche.

## Resultado

- **Didit sin webhook** (la cuenta de Didit es de otro proyecto):
  - la persona escribe LISTO en el chat, o vuelve por `/didit/retorno`;
  - `estado_verificacion` le pide la decisión al backend y el agente le avisa en su conversación.
- **Ubicación en ADK:** se escribe `[ubicación] lat …, lon …`, que el agente ya entendía.
- **Prueba hecha en producción con dos personas reales:**
  - Cristian (cliente) retiró 200.000 COP en la tienda de Magno (tendero);
  - pasó por Didit (alta y retiro), cupo aprobado una vez, APROBAR en el chat y pago por Open Payments en el Rafiki
    propio;
  - entrega confirmada por los dos.
- **Problemas encontrados en los logs y arreglados en el backend:**
  - la verificación facial del retiro no encontraba la cara del alta (`vendor_data`);
  - la reserva buscaba el efectivo del día UTC y no del día de Colombia.
- **En `contexto-caja-de-barrio`:** `prueba-punta-a-punta.md`, `panel-de-control-v3.md` y `estado-prueba-e2e.md`.
