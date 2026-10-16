"""Configuración del agente leída de variables de entorno (.env)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "simulado": herramientas en memoria dentro del agente (para probar sin MCP).
    # "mcp": herramientas reales vía servidores MCP por streamable HTTP.
    modo_herramientas: Literal["simulado", "mcp"] = "simulado"
    modelo: str = "gemini-3.5-flash"

    google_api_key: str = ""
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_api_version: str = "v21.0"

    mcp_pagos_url: str = "http://mcp-pagos:8101/mcp"
    mcp_mapa_url: str = "http://mcp-mapa:8102/mcp"
    mcp_caja_url: str = "http://mcp-caja:8103/mcp"
    mcp_identidad_url: str = "http://mcp-identidad:8104/mcp"

    public_base_url: str = "http://localhost:8080"
    # Token que el backend manda en X-Servicio-Token al llamar /internal/avisos. Vacío: se rechaza todo.
    servicio_token: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
