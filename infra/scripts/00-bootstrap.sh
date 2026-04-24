#!/usr/bin/env bash
# Enables required GCP APIs. Idempotent.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "${SCRIPT_DIR}/_common.sh"

require_cmd gcloud
ensure_project

APIS=(
  run.googleapis.com
  artifactregistry.googleapis.com
  firestore.googleapis.com
  secretmanager.googleapis.com
  cloudscheduler.googleapis.com
  storage.googleapis.com
  logging.googleapis.com
  generativelanguage.googleapis.com
  cloudbuild.googleapis.com
  iamcredentials.googleapis.com
)

log "Enabling ${#APIS[@]} APIs (this may take a minute)..."
gcloud services enable "${APIS[@]}"
log "Done."
