#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

require_cmd gcloud
ensure_project

if gcloud firestore databases describe --database="(default)" >/dev/null 2>&1; then
  log "Default Firestore database exists, skip."
else
  log "Creating Firestore (Native mode) in ${REGION}"
  gcloud firestore databases create --location="${REGION}" --type=firestore-native
fi
log "Done."
