#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

require_cmd gcloud
ensure_project

PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')
POOL_ID="github-pool"
PROVIDER_ID="github-provider"

if gcloud iam workload-identity-pools describe "${POOL_ID}" --location=global >/dev/null 2>&1; then
  log "Pool ${POOL_ID} exists, skip create."
else
  log "Creating WIF pool ${POOL_ID}"
  gcloud iam workload-identity-pools create "${POOL_ID}" \
    --location=global --display-name="GitHub Actions Pool"
fi

if gcloud iam workload-identity-pools providers describe "${PROVIDER_ID}" \
     --workload-identity-pool="${POOL_ID}" --location=global >/dev/null 2>&1; then
  log "Provider ${PROVIDER_ID} exists, skip create."
else
  log "Creating OIDC provider ${PROVIDER_ID} for repo ${GH_REPO}"
  gcloud iam workload-identity-pools providers create-oidc "${PROVIDER_ID}" \
    --workload-identity-pool="${POOL_ID}" --location=global \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition="attribute.repository == '${GH_REPO}'"
fi

log "Allowing repo ${GH_REPO} to impersonate ${DEPLOYER_SA}"
gcloud iam service-accounts add-iam-policy-binding "${DEPLOYER_SA}" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${GH_REPO}" >/dev/null

cat <<EOF

============================================================
WIF setup complete.

ADD THIS TO GitHub repo Settings → Secrets and variables → Actions:

  Name:  GCP_PROJECT_NUMBER
  Value: ${PROJECT_NUMBER}

============================================================
EOF
