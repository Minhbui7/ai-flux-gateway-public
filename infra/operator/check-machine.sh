#!/usr/bin/env bash
set -euo pipefail
cloud-init status --wait
test -f /var/lib/cloud/instance/aiflux-machine-bootstrap-complete
test "$(systemctl is-active walinuxagent)" = active
test "$(systemctl is-active docker)" = active
if systemctl is-active --quiet ssh.service || systemctl is-active --quiet ssh.socket; then
  echo "ERROR: SSH must remain disabled" >&2
  exit 1
fi
getent hosts github.com
curl --fail --silent --show-error --connect-timeout 15 --max-time 30 --output /dev/null https://github.com
echo "Machine checks passed; Azure CLI, Terraform, private state DNS/access and GitHub registration remain separate acceptance gates."
