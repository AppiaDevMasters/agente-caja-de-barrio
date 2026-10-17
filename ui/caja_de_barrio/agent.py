"""El mismo coordinador que atiende WhatsApp, expuesto a la UI de ADK.

Cada persona abre la UI con su número como userId, por ejemplo:
    https://agente.cajadebarrio.lat/dev-ui/?app=caja_de_barrio&userId=573001234567
"""

from agente.agentes import crear_agente_raiz

root_agent = crear_agente_raiz()
