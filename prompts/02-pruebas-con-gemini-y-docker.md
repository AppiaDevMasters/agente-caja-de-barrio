# 02 · Docker, Gemini 3.5 y primeras pruebas del agente

Herramienta: Claude Code (Claude Opus 5.5). Fecha: 2026-10-16.

## Prompts (textuales)

> y dockerizalo, para irlo corriendo aquí, ademas, donde está el .env?

> el modelo es el 3.5, es el que utilizaremos en el gemini, ya agregué en el .env
> docker ya se levantó

> que falta?

> ya la llave está

> me dices cuando ya entran las llaves de didit, de verifik de, open payments

> o esas llaves van en el .env del back, esas ya van en el .env del back, verdad?

> las llaves las debe poner el backend cuando active un ngrok o un tunnel verdad?

## Resultado

- `docker-compose.yml` propio del agente (puerto 8088, configurable con `AGENTE_PUERTO`).
- Modelo `gemini-3.5-flash`.
- Pruebas reales por `/chat` de las tres escenas (retiro, remesa en USD, fraude). Se encontró un bucle:
  el especialista de pagos no recibía las billeteras y las inventaba. Se corrigió guardando en el
  estado de la sesión las billeteras, ids y monto e inyectándolos en las instrucciones de cada
  especialista, prohibiendo reintentos con datos inventados y poniendo topes de llamadas
  (10 herramientas por especialista, 30 llamadas al modelo por mensaje).
- Log de cada llamada a herramienta con `reserva_id`.
