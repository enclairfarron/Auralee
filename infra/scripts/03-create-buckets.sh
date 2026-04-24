#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

require_cmd gcloud
require_cmd gsutil
ensure_project

if gsutil ls "gs://${RAW_BUCKET}" >/dev/null 2>&1; then
  log "Bucket gs://${RAW_BUCKET} exists, skip."
else
  log "Creating bucket gs://${RAW_BUCKET}"
  gsutil mb -p "${PROJECT_ID}" -c STANDARD -l "${REGION}" -b on "gs://${RAW_BUCKET}"
fi

# Lifecycle: transition to Nearline at 90 days
cat <<EOF >/tmp/lifecycle.json
{
  "lifecycle": {
    "rule": [
      { "action": { "type": "SetStorageClass", "storageClass": "NEARLINE" },
        "condition": { "age": 90, "matchesStorageClass": ["STANDARD"] } }
    ]
  }
}
EOF
gsutil lifecycle set /tmp/lifecycle.json "gs://${RAW_BUCKET}"
rm /tmp/lifecycle.json
log "Done."
