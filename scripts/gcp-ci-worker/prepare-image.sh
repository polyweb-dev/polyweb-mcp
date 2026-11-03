#!/usr/bin/env bash
# Runs as root on a fresh Ubuntu 24.04 builder. Never join Headscale here.
set -euo pipefail
trap 'echo CI_IMAGE_BAKE_FAILED >&2' ERR
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl --retry 3 -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
source /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io
curl --retry 3 -fsSL https://tailscale.com/install.sh | sh
systemctl enable --now docker tailscaled
docker pull woodpeckerci/woodpecker-agent:v3
docker pull ghcr.io/astral-sh/uv:python3.12-bookworm-slim
docker image inspect woodpeckerci/woodpecker-agent:v3 ghcr.io/astral-sh/uv:python3.12-bookworm-slim --format '{{json .RepoDigests}}'
systemctl is-enabled docker tailscaled
test -z "$(docker ps -aq)"
# Preserve Docker's layer cache, remove per-machine identity and build logs.
systemctl stop tailscaled docker docker.socket containerd
rm -rf /var/lib/tailscale/*
apt-get clean
rm -rf /var/lib/apt/lists/*
rm -f /etc/ssh/ssh_host_*
cloud-init clean --logs --machine-id
sync
echo CI_IMAGE_BAKE_SUCCESS
