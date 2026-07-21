#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

require_cmd gcloud
ensure_project

create_secret() {
  local name="$1"
  if gcloud secrets describe "${name}" >/dev/null 2>&1; then
    log "Secret ${name} exists, skip."
  else
    log "Creating empty secret ${name}"
    gcloud secrets create "${name}" --replication-policy=automatic
  fi
}

create_secret WSJ_COOKIE
create_secret ADMIN_TOKEN

log "Done. Populate values manually:"
log "  pbpaste | gcloud secrets versions add WSJ_COOKIE --data-file=-"
log '  admin_token=$(openssl rand -hex 32); printf %s "${admin_token}" | gcloud secrets versions add ADMIN_TOKEN --data-file=-'
