#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

require_cmd gcloud
ensure_project

SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" --format='value(status.url)')
if [[ -z "${SERVICE_URL}" ]]; then
  echo "Cloud Run service ${SERVICE_NAME} not found; deploy first."; exit 1
fi
log "Service URL: ${SERVICE_URL}"

upsert_job() {
  local name="$1"
  local schedule="$2"
  local uri="$3"

  local admin_token
  admin_token=$(gcloud secrets versions access latest --secret=ADMIN_TOKEN)

  if gcloud scheduler jobs describe "${name}" --location="${REGION}" >/dev/null 2>&1; then
    log "Updating scheduler job ${name}"
    gcloud scheduler jobs update http "${name}" \
      --location="${REGION}" \
      --schedule="${schedule}" \
      --time-zone="Etc/UTC" \
      --http-method=POST \
      --uri="${uri}" \
      --oidc-service-account-email="${SCHEDULER_SA}" \
      --oidc-token-audience="${SERVICE_URL}" \
      --update-headers="X-Admin-Token=${admin_token}" \
      --attempt-deadline=600s
  else
    log "Creating scheduler job ${name}"
    gcloud scheduler jobs create http "${name}" \
      --location="${REGION}" \
      --schedule="${schedule}" \
      --time-zone="Etc/UTC" \
      --http-method=POST \
      --uri="${uri}" \
      --oidc-service-account-email="${SCHEDULER_SA}" \
      --oidc-token-audience="${SERVICE_URL}" \
      --headers="X-Admin-Token=${admin_token}" \
      --attempt-deadline=600s
  fi
}

upsert_job scrape-hn-hourly        "5 * * * *"  "${SERVICE_URL}/cron/scrape?source=hn"
upsert_job scrape-reuters-hourly   "15 * * * *" "${SERVICE_URL}/cron/scrape?source=reuters"
upsert_job scrape-wsj-hourly       "25 * * * *" "${SERVICE_URL}/cron/scrape?source=wsj"
upsert_job refresh-prices-daily    "0 21 * * *" "${SERVICE_URL}/cron/refresh-prices"
upsert_job aggregate-metrics-daily "55 23 * * *" "${SERVICE_URL}/cron/aggregate-metrics"
upsert_job eval-judge-daily        "30 4 * * *" "${SERVICE_URL}/cron/eval-judge"

log "Done. 6 scheduler jobs active."
log "NOTE: ADMIN_TOKEN is fetched from Secret Manager at job-create time."
log "If you rotate ADMIN_TOKEN, re-run this script to refresh scheduler configs."
