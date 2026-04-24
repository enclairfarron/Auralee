#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

require_cmd gcloud
ensure_project

create_sa() {
  local name="$1"
  local desc="$2"
  if gcloud iam service-accounts describe "${name}@${PROJECT_ID}.iam.gserviceaccount.com" >/dev/null 2>&1; then
    log "SA ${name} exists, skip."
  else
    log "Creating SA ${name}"
    gcloud iam service-accounts create "${name}" --display-name="${desc}"
  fi
}

create_sa auralee-runtime    "Cloud Run runtime for auralee-api"
create_sa auralee-scheduler  "Cloud Scheduler invoker"
create_sa auralee-deployer   "GitHub Actions deployer"
create_sa auralee-cloudbuild "Cloud Build worker"

log "Done. 4 service accounts ready."
