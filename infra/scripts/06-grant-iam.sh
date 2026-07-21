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
            roles/aiplatform.user \
            roles/logging.logWriter \
            roles/cloudtrace.agent ; do
  bind_project_role "${RUNTIME_SA}" "${role}"
done
log "Granting storage.objectAdmin on ${RAW_BUCKET} to runtime SA"
gcloud storage buckets add-iam-policy-binding "gs://${RAW_BUCKET}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role=roles/storage.objectAdmin >/dev/null

# Cloud Build worker SA
for role in roles/artifactregistry.writer \
            roles/logging.logWriter \
            roles/storage.objectUser ; do
  bind_project_role "${CLOUDBUILD_SA}" "${role}"
done

# Deployer SA — needs builds.editor + run.developer + serviceUsageConsumer
# (for `gcloud builds submit` API call) + logs.viewer (for build status polling)
for role in roles/cloudbuild.builds.editor \
            roles/run.developer \
            roles/serviceusage.serviceUsageConsumer \
            roles/logging.viewer ; do
  bind_project_role "${DEPLOYER_SA}" "${role}"
done

# Deployer needs access to Cloud Build's auto-created staging bucket to
# upload source tarball. The bucket is created on first build run by Cloud
# Build itself (named ${PROJECT_ID}_cloudbuild). If the bucket doesn't exist
# yet (first-ever build), this binding is skipped — re-run this script once
# the bucket exists.
STAGING_BUCKET="gs://${PROJECT_ID}_cloudbuild"
if gcloud storage buckets describe "${STAGING_BUCKET}" >/dev/null 2>&1; then
  log "Granting deployer storage.objectAdmin on ${STAGING_BUCKET}"
  gcloud storage buckets add-iam-policy-binding "${STAGING_BUCKET}" \
    --member="serviceAccount:${DEPLOYER_SA}" --role=roles/storage.objectAdmin >/dev/null
else
  log "Cloud Build staging bucket ${STAGING_BUCKET} does not exist yet (first build will create it)."
  log "Re-run this script after first successful local 'gcloud builds submit' to grant deployer access."
fi

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
