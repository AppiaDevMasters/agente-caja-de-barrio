FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY agente ./agente
COPY dev ./dev
COPY ui ./ui

EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"
# Un solo proceso: la UI de ADK (/dev-ui) y el gateway (WhatsApp, Didit, billetera, avisos).
CMD ["uvicorn", "agente.servidor:app", "--host", "0.0.0.0", "--port", "8080"]
