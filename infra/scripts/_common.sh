#!/usr/bin/env bash
# Sourced by all setup scripts. Defines exported vars + helpers.
set -euo pipefail

export PROJECT_ID="auralee-api-server"
export REGION="us-east1"
export AR_REPO="api"
export SERVICE_NAME="auralee-api"
export RAW_BUCKET="${PROJECT_ID}-raw"

export RUNTIME_SA="auralee-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
export SCHEDULER_SA="auralee-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"
export DEPLOYER_SA="auralee-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
export CLOUDBUILD_SA="auralee-cloudbuild@${PROJECT_ID}.iam.gserviceaccount.com"

export GH_REPO="enclairfarron/Auralee"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }
}

ensure_project() {
  local current
  current=$(gcloud config get-value project 2>/dev/null || true)
  if [[ "${current}" != "${PROJECT_ID}" ]]; then
    echo "Setting active project to ${PROJECT_ID}"
    gcloud config set project "${PROJECT_ID}"
  fi
}

log() { echo "[$(date +%H:%M:%S)] $*"; }
