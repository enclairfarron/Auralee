#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

require_cmd gcloud
ensure_project

bind_project_role() {
  local member="$1"
  local role="$2"
  log "Bind ${role} to ${member}"
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${member}" --role="${role}" --condition=None >/dev/null
}

# Runtime SA
for role in roles/datastore.user \
            roles/secretmanager.secretAccessor \
            roles/logging.logWriter \
            roles/cloudtrace.agent ; do
  bind_project_role "${RUNTIME_SA}" "${role}"
done
log "Granting storage.objectAdmin on ${RAW_BUCKET} to runtime SA"
gsutil iam ch "serviceAccount:${RUNTIME_SA}:roles/storage.objectAdmin" "gs://${RAW_BUCKET}"

# Cloud Build worker SA
for role in roles/artifactregistry.writer \
            roles/logging.logWriter \
            roles/storage.objectUser ; do
  bind_project_role "${CLOUDBUILD_SA}" "${role}"
done

# Deployer SA
for role in roles/cloudbuild.builds.editor \
            roles/run.developer ; do
  bind_project_role "${DEPLOYER_SA}" "${role}"
done

# Deployer can act-as runtime + cloudbuild SAs
log "Allow deployer to impersonate runtime and cloudbuild SAs"
gcloud iam service-accounts add-iam-policy-binding "${RUNTIME_SA}" \
  --member="serviceAccount:${DEPLOYER_SA}" --role=roles/iam.serviceAccountUser >/dev/null
gcloud iam service-accounts add-iam-policy-binding "${CLOUDBUILD_SA}" \
  --member="serviceAccount:${DEPLOYER_SA}" --role=roles/iam.serviceAccountUser >/dev/null

# Scheduler SA can invoke the Cloud Run service (run once service is deployed).
if gcloud run services describe "${SERVICE_NAME}" --region="${REGION}" >/dev/null 2>&1; then
  log "Granting run.invoker on ${SERVICE_NAME} to scheduler SA"
  gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
    --region="${REGION}" \
    --member="serviceAccount:${SCHEDULER_SA}" \
    --role=roles/run.invoker >/dev/null
else
  log "Service ${SERVICE_NAME} not yet deployed; re-run 06 after first deploy."
fi

log "Done."
