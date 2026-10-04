#!/bin/sh
set -eu
image=${1:?image required}
name=syncthing-mcp-smoke
cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM
token=$(openssl rand -hex 32)
docker run -d --name "$name" --read-only --cap-drop=ALL --security-opt=no-new-privileges \
  -p 127.0.0.1:18088:8080 \
  -e SYNCTHING_URL=http://127.0.0.1:8384 -e SYNCTHING_API_KEY=disposable-test-backend-key \
  -e SYNCTHING_MCP_TRANSPORT=http -e SYNCTHING_MCP_HOST=0.0.0.0 \
  -e SYNCTHING_MCP_PORT=8080 -e SYNCTHING_MCP_AUTH_TOKEN="$token" \
  -e 'SYNCTHING_MCP_ALLOWED_HOSTS=["127.0.0.1:18088"]' "$image" >/dev/null
for attempt in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:18088/healthz >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS http://127.0.0.1:18088/healthz
test "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18088/mcp)" = 401
curl -fsS http://127.0.0.1:18088/mcp -H "Authorization: Bearer $token" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}}' | jq -e '.result.serverInfo.name == "syncthing-mcp"'
docker exec "$name" python -c 'import os; assert os.getuid() == 10001'
