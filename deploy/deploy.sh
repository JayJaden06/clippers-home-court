#!/usr/bin/env bash
# Build the ingest image and deploy it as a Cloud Run Job triggered daily by Cloud Scheduler.
# Safe to re-run: every step creates the resource or updates it in place.
#
#   PROJECT_ID=my-proj BUCKET=my-proj-clippers ./deploy/deploy.sh
#
# Optional: REGION (default us-west1), SCHEDULE (cron, default 09:00 Pacific),
#           PUBLIC_BUCKET=1 to let the public dashboard read the data anonymously,
#           NBA_API_PROXY if stats.nba.com blocks Cloud Run's egress IPs.
set -euo pipefail

: "${PROJECT_ID:?set PROJECT_ID}"
: "${BUCKET:?set BUCKET}"
REGION="${REGION:-us-west1}"
SCHEDULE="${SCHEDULE:-0 9 * * *}"
JOB=clippers-ingest
REPO=clippers
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$JOB:$(git rev-parse --short HEAD 2>/dev/null || date +%s)"
JOB_SA="$JOB@$PROJECT_ID.iam.gserviceaccount.com"
SCHED_SA="$JOB-scheduler@$PROJECT_ID.iam.gserviceaccount.com"

gcloud config set project "$PROJECT_ID" >/dev/null

echo "==> Enabling APIs"
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com storage.googleapis.com

echo "==> Bucket gs://$BUCKET"
gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1 ||
  gcloud storage buckets create "gs://$BUCKET" --location="$REGION" --uniform-bucket-level-access
if [[ "${PUBLIC_BUCKET:-0}" == 1 ]]; then
  gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
    --member=allUsers --role=roles/storage.objectViewer >/dev/null
fi

echo "==> Service accounts"
gcloud iam service-accounts describe "$JOB_SA" >/dev/null 2>&1 ||
  gcloud iam service-accounts create "$JOB" --display-name="Clippers ingest job"
gcloud iam service-accounts describe "$SCHED_SA" >/dev/null 2>&1 ||
  gcloud iam service-accounts create "$JOB-scheduler" --display-name="Clippers ingest scheduler"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$JOB_SA" --role=roles/storage.objectAdmin >/dev/null

echo "==> Image $IMAGE"
gcloud artifacts repositories describe "$REPO" --location="$REGION" >/dev/null 2>&1 ||
  gcloud artifacts repositories create "$REPO" --repository-format=docker --location="$REGION"
gcloud builds submit --tag "$IMAGE" .

echo "==> Cloud Run Job $JOB"
ENV_VARS="DATA_URI=gs://$BUCKET"
[[ -n "${NBA_API_PROXY:-}" ]] && ENV_VARS="$ENV_VARS,NBA_API_PROXY=$NBA_API_PROXY"
gcloud run jobs deploy "$JOB" \
  --image="$IMAGE" \
  --region="$REGION" \
  --service-account="$JOB_SA" \
  --set-env-vars="$ENV_VARS" \
  --memory=1Gi \
  --task-timeout=30m \
  --max-retries=1

gcloud run jobs add-iam-policy-binding "$JOB" --region="$REGION" \
  --member="serviceAccount:$SCHED_SA" --role=roles/run.invoker >/dev/null

echo "==> Cloud Scheduler ($SCHEDULE, America/Los_Angeles)"
RUN_URI="https://run.googleapis.com/v2/projects/$PROJECT_ID/locations/$REGION/jobs/$JOB:run"
SCHED_ARGS=(
  --location="$REGION"
  --schedule="$SCHEDULE"
  --time-zone=America/Los_Angeles
  --uri="$RUN_URI"
  --http-method=POST
  --oauth-service-account-email="$SCHED_SA"
)
if gcloud scheduler jobs describe "$JOB-daily" --location="$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$JOB-daily" "${SCHED_ARGS[@]}"
else
  gcloud scheduler jobs create http "$JOB-daily" "${SCHED_ARGS[@]}"
fi

echo
echo "Deployed. Run it now with:"
echo "  gcloud run jobs execute $JOB --region=$REGION --wait"
