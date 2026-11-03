#!/usr/bin/env bash
# Requires an authenticated gcloud CLI with Compute instance/disk/image rights.
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT=${GCP_PROJECT_ID:-polyweb-513423}
ZONE=${GCP_ZONE:-us-central1-a}
IMAGE=${1:-woodpecker-worker-$(date -u +%Y%m%d-%H%M%S)}
BUILDER="${IMAGE}-builder"
gcloud_cmd=(gcloud --quiet --project="$PROJECT")
cleanup() {
  "${gcloud_cmd[@]}" compute instances delete "$BUILDER" --zone="$ZONE" --delete-disks=all || {
    echo "Cleanup failed: delete $BUILDER in $ZONE manually." >&2
    return 1
  }
}
# Refuse an existing name before registering cleanup: never delete someone else's VM.
if "${gcloud_cmd[@]}" compute instances describe "$BUILDER" --zone="$ZONE" >/dev/null 2>&1; then
  echo "Builder already exists: $BUILDER" >&2
  exit 1
fi
trap cleanup EXIT
"${gcloud_cmd[@]}" compute instances create "$BUILDER" \
  --zone="$ZONE" --machine-type=e2-standard-4 \
  --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
  --boot-disk-size=50GB --boot-disk-type=pd-balanced \
  --no-service-account --no-scopes \
  --labels=role=ci-image-builder,managed-by=woodpecker \
  --metadata-from-file="startup-script=$SCRIPT_DIR/prepare-image.sh"
deadline=$((SECONDS + 1200))
while (( SECONDS < deadline )); do
  output=$("${gcloud_cmd[@]}" compute instances get-serial-port-output "$BUILDER" --zone="$ZONE" 2>/dev/null || true)
  if [[ "$output" == *CI_IMAGE_BAKE_FAILED* ]]; then
    printf '%s\n' "$output" >&2
    exit 1
  fi
  if [[ "$output" == *CI_IMAGE_BAKE_SUCCESS* ]]; then
    printf '%s\n' "$output"
    break
  fi
  sleep 10
done
if [[ "$output" != *CI_IMAGE_BAKE_SUCCESS* ]]; then
  printf 'Image preparation timed out. Last serial output:\n%s\n' "$output" >&2
  exit 1
fi
"${gcloud_cmd[@]}" compute instances stop "$BUILDER" --zone="$ZONE"
"${gcloud_cmd[@]}" compute images create "$IMAGE" \
  --source-disk="$BUILDER" --source-disk-zone="$ZONE" \
  --family=woodpecker-ci-worker --storage-location=us-central1 \
  --labels=role=ci-worker,managed-by=woodpecker \
  --description="Ubuntu 24.04; Docker CE; Tailscale; Woodpecker v3 and uv Python 3.12 cache. See scripts/gcp-ci-worker."
"${gcloud_cmd[@]}" compute images describe "$IMAGE" --format='yaml(name,family,status,creationTimestamp)'
