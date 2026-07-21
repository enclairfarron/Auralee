#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

require_cmd gcloud
ensure_project

create_index() {
  local collection_group="$1"
  shift
  local output

  if output=$(gcloud firestore indexes composite create \
    --database="(default)" \
    --collection-group="${collection_group}" \
    --query-scope=collection \
    --async \
    "$@" 2>&1); then
    log "Requested ${collection_group} index: $*"
    return
  fi

  if [[ "${output}" == *"ALREADY_EXISTS"* || "${output}" == *"already exists"* ]]; then
    log "Index already exists for ${collection_group}: $*"
    return
  fi

  echo "${output}" >&2
  return 1
}

# Keep this list in sync with infra/firestore.indexes.json. The JSON file is the
# reviewable manifest; this script avoids requiring the Firebase CLI.
create_index articles \
  --field-config=field-path=source,order=ascending \
  --field-config=field-path=processed_at,order=descending

create_index articles \
  --field-config=field-path=eval_score,order=ascending \
  --field-config=field-path=processed_at,order=ascending

create_index runs \
  --field-config=field-path=kind,order=ascending \
  --field-config=field-path=started_at,order=descending

create_index runs \
  --field-config=field-path=source,order=ascending \
  --field-config=field-path=started_at,order=descending

create_index runs \
  --field-config=field-path=kind,order=ascending \
  --field-config=field-path=source,order=ascending \
  --field-config=field-path=started_at,order=descending

log "Index creation requests submitted. Wait until every index reports READY:"
log '  gcloud firestore indexes composite list --database="(default)" --format="table(name.basename(),state,collectionGroup,fields)"'
