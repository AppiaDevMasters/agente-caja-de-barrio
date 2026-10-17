#!/usr/bin/env bash
#
# Instala el agente (UI de ADK + gateway) y los cuatro MCP en el VPS del backend.
#
# Requisitos en el VPS, uno al lado del otro:
#   backend-caja-de-barrio/   ya instalado con su deploy/instalar.sh (red, Caddy, dominio, token)
#   agente-caja-de-barrio/    este repo, con su .env (GOOGLE_API_KEY y MODELO)
#   mcp-{identidad,mapa,caja,pagos}-caja-de-barrio/
#
# Uso, desde la raíz de este repo:
#   sudo ./deploy/instalar.sh
set -euo pipefail

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$raiz"
backend_env="${BACKEND_DIR:-$raiz/../backend-caja-de-barrio}/rafiki/.env"

paso() { printf '\n==> %s\n' "$*"; }
env_val() { sed -n "s/^$1=//p" "$2" | head -n 1; }

paso "Requisitos"
[ -f "$backend_env" ] || { echo "No encuentro $backend_env: instala primero el backend." >&2; exit 1; }
[ -f .env ] || { echo "Falta .env (copia .env.example y pon GOOGLE_API_KEY y MODELO)." >&2; exit 1; }
grep -q '^GOOGLE_API_KEY=.\+' .env || { echo "Falta GOOGLE_API_KEY en .env." >&2; exit 1; }
for m in identidad mapa caja pagos; do
  [ -d "../mcp-$m-caja-de-barrio" ] || { echo "Falta ../mcp-$m-caja-de-barrio." >&2; exit 1; }
done
docker network inspect rafiki-caja-barrio_rafiki >/dev/null || {
  echo "No existe la red del backend: levanta primero su stack." >&2; exit 1; }

# El token y el dominio son los del backend: los MCP llaman /internal con ese token y el
# backend llama /internal/avisos del agente con el mismo.
SERVICIO_TOKEN="$(env_val SERVICIO_TOKEN "$backend_env")"
DOMINIO="$(env_val DOMINIO "$backend_env")"
export SERVICIO_TOKEN DOMINIO
[ -n "$SERVICIO_TOKEN" ] && [ -n "$DOMINIO" ] || { echo "Al backend le falta SERVICIO_TOKEN o DOMINIO." >&2; exit 1; }
echo "Dominio: $DOMINIO"

paso "Levantando agente y MCP"
docker compose -f deploy/compose.vps.yml up -d --build

paso "Esperando al agente"
for _ in $(seq 1 40); do
  estado="$(docker inspect -f '{{.State.Health.Status}}' agente 2>/dev/null || true)"
  [ "$estado" = healthy ] && break
  sleep 3
done
[ "$estado" = healthy ] || { echo "El agente no quedó sano; revisa: docker logs agente" >&2; exit 1; }

paso "Verificación"
printf '%-50s ' "https://agente.$DOMINIO/health"
curl -fsS --retry 10 --retry-delay 3 --retry-all-errors "https://agente.$DOMINIO/health" || echo "FALLÓ"
echo
printf '%-50s ' "UI de ADK sin usuario y clave"
curl -sS -o /dev/null -w '%{http_code}\n' "https://agente.$DOMINIO/dev-ui/"

cat <<EOF

Listo. Cada persona abre la UI de ADK con su número como userId (usuario y clave: los de la UI de Rafiki,
en ../backend-caja-de-barrio/deploy/.credenciales-admin):

  https://agente.$DOMINIO/dev-ui/?app=caja_de_barrio&userId=<número con indicativo, sin +>

Webhooks públicos (sin clave): https://agente.$DOMINIO/webhook/whatsapp · /webhook/didit · /op/finish
EOF
