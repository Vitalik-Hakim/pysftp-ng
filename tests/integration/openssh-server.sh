#!/usr/bin/env bash
# Start a throwaway OpenSSH server in Docker for the integration tests, then
# print the PYSFTP_INTEGRATION_* settings that point the tests at it.
#
#   export $(tests/integration/openssh-server.sh)
#   python -m pytest tests/integration
#   docker rm -f pysftp-openssh
#
# In GitHub Actions, append the output to "$GITHUB_ENV" instead.
set -euo pipefail

image="lscr.io/linuxserver/openssh-server:10.3_p1-r1-ls241@sha256:0b46c755aac07057908077f2c7ff14f0ad923970bb6a3a67bcd008e72fa60050"
name=pysftp-openssh
host=127.0.0.1
port=2222
user=pysftp
dir=$(mktemp -d)
password=$(openssl rand -hex 16)

ssh-keygen -q -t ed25519 -N "" -C pysftp-integration -f "$dir/id_ed25519"
docker run -d --rm --name "$name" -p "$host:$port:2222" \
  -e USER_NAME="$user" \
  -e PASSWORD_ACCESS=true \
  -e USER_PASSWORD="$password" \
  -e PUBLIC_KEY="$(cat "$dir/id_ed25519.pub")" \
  "$image" >/dev/null

# sshd needs a few seconds to start. Wait until it answers with its host keys.
for _ in $(seq 60); do
  if ssh-keyscan -p "$port" "$host" >"$dir/known_hosts" 2>/dev/null && [ -s "$dir/known_hosts" ]; then
    break
  fi
  sleep 1
done
if [ ! -s "$dir/known_hosts" ]; then
  echo "The OpenSSH server didn't start:" >&2
  docker logs "$name" >&2
  exit 1
fi

cat <<EOF
PYSFTP_INTEGRATION_HOST=$host
PYSFTP_INTEGRATION_PORT=$port
PYSFTP_INTEGRATION_USER=$user
PYSFTP_INTEGRATION_PASSWORD=$password
PYSFTP_INTEGRATION_KEY=$dir/id_ed25519
PYSFTP_INTEGRATION_KNOWN_HOSTS=$dir/known_hosts
EOF
