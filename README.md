# Sentiment Analysis Platform

Minimal production-style sentiment inference system on AWS using Python Lambda, API Gateway, SQS, DynamoDB, S3, CloudFront, and Terraform.

## Project Overview

- `POST /analyze`: synchronous sentiment inference.
- `POST /batch`: async batch submission (`job_id` returned).
- `GET /history`: user or batch history lookup.
- `GET /jobs/{id}`: async job status lookup.
- `POST /jobs`: exists in backend code but is not exposed in API Gateway.

## Prerequisites

- Python 3.11+
- Terraform 1.6+
- AWS CLI v2 configured for your account/region
- GitHub repository with Actions enabled (for CI/CD deploy path)

## Architecture

```mermaid
flowchart LR
    Browser[Browser] --> CF[S3 + CloudFront Frontend]
    Browser --> API[API Gateway]

    API --> Analyze[Lambda: sentiment_analyzer]
    API --> Submitter[Lambda: batch_processor (batch_submitter)]
    API --> History[Lambda: history_handler]
    API --> JobStatus[Lambda: job_status_handler]

    Submitter --> Queue[SQS batch_jobs]
    Queue --> Worker[Lambda: batch_worker]
    Queue --> DLQ[SQS batch_jobs_dlq]

    Analyze --> DDB[(DynamoDB)]
    Submitter --> DDB
    Worker --> DDB
    History --> DDB
    JobStatus --> DDB

    Analyze --> Model[(S3 model assets)]
    Worker --> Model
```

If Mermaid does not render: frontend is served from S3/CloudFront, API is API Gateway + Lambda, async batch uses SQS + worker Lambda + DLQ, data is in DynamoDB, model assets are in S3.

## Quick Start

```bash
cd /Users/spartan/Dev/school/Cloud/sentiment-analysis

python3 -m venv .venv
source .venv/bin/activate

python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 -m pip install -r backend/sentiment_analyzer/requirements.txt
python3 -m pip install -r backend/batch_processor/requirements.txt
python3 -m pip install -r backend/history/requirements.txt

# Optional ONNX export (for local model assets)
python3 -m pip install -r requirements-export.txt
python3 export_onnx.py

# Terminal 1: local API
python3 local_server.py

# Terminal 2: local frontend
python3 -m http.server 8080 --directory frontend
```

Open `http://localhost:8080`.

## Local API Smoke Tests

```bash
curl -sS -X POST http://localhost:5000/analyze \
  -H "Content-Type: application/json" \
  -d '{"text":"I love this!","user_id":"local"}'
```

```bash
curl -sS -X POST http://localhost:5000/batch \
  -H "Content-Type: application/json" \
  -d '{"texts":["great","bad"],"user_id":"local"}'
```

```bash
curl -sS "http://localhost:5000/history?user_id=local&limit=10"
```

## Deploy

### CI/CD (Primary Path)

Push to `main`; `.github/workflows/deploy.yml` does:

1. Export/validate ONNX assets.
2. `terraform init/plan/apply` in `sentiment-analysis-infrastructure`.
3. `python update_config.py` to generate `deploy_config.json` from Terraform outputs.
4. `python deploy_all.py` to deploy all backend Lambdas and frontend assets.
5. Smoke test `POST /analyze`.

Required GitHub secrets:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `TF_STATE_BUCKET`
- `ALERT_EMAIL`
- `THIRD_PARTY_API_KEY`

Optional GitHub variable:

- `AWS_REGION` (defaults to `us-west-2`)

### Manual Infra + App Deploy

```bash
cd /Users/spartan/Dev/school/Cloud/sentiment-analysis/sentiment-analysis-infrastructure
export AWS_PAGER=""
cp terraform.tfvars.example terraform.tfvars

# edit terraform.tfvars with required values
terraform init
terraform plan
terraform apply
```

```bash
cd /Users/spartan/Dev/school/Cloud/sentiment-analysis
source .venv/bin/activate
export AWS_PAGER=""
python3 update_config.py
python3 deploy_all.py
```

## API Endpoints

Deployed API Gateway routes:

- `POST /analyze`
- `POST /batch`
- `GET /history`
- `GET /jobs/{id}`

Not exposed via API Gateway:

- `POST /jobs`

Get deployed base URL:

```bash
API_URL="$(terraform -chdir=/Users/spartan/Dev/school/Cloud/sentiment-analysis/sentiment-analysis-infrastructure output -raw api_endpoint)"
echo "$API_URL"
```

## Example Requests/Responses

### `POST /analyze`

```bash
curl -sS -X POST "$API_URL/analyze" \
  -H "Content-Type: application/json" \
  -d '{"text":"I absolutely love this service","user_id":"demo"}'
```

Example response:

```json
{
  "user_id": "demo",
  "sentiment": "POSITIVE",
  "confidence": 0.99,
  "model_version": "1.0.0"
}
```

### `POST /batch`

```bash
curl -sS -X POST "$API_URL/batch" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"demo","input_mode":"inline","texts":["great","bad"]}'
```

Example response:

```json
{
  "job_id": "job-1712890000-ab12cd34",
  "status": "QUEUED",
  "model_version": "1.0.0",
  "submitted_at": "2026-04-12T10:00:00+00:00"
}
```

### `GET /jobs/{id}`

```bash
curl -sS "$API_URL/jobs/job-1712890000-ab12cd34"
```

Example response:

```json
{
  "job_id": "job-1712890000-ab12cd34",
  "status": "COMPLETED",
  "progress": {
    "processed_rows": 2,
    "total_rows": 2,
    "success_count": 2,
    "failed_count": 0,
    "percent": 100
  },
  "result_location": "dynamodb://table/JOB#job-1712890000-ab12cd34",
  "model_version": "1.0.0"
}
```

### `GET /history`

```bash
curl -sS "$API_URL/history?user_id=demo&limit=10"
```

Example response:

```json
{
  "user_id": "demo",
  "count": 1,
  "history": [
    {
      "type": "ANALYSIS",
      "sentiment": "POSITIVE",
      "confidence": 0.99
    }
  ]
}
```

## Deployment Alignment (Current)

The following are aligned across Terraform, `deploy_all.py`, `update_config.py`, and generated `deploy_config.json`:

- `sentiment_analyzer` -> `lambda_function.lambda_handler`
- `batch_processor` -> `batch_submitter.lambda_handler`
- `batch_worker` -> `batch_worker.lambda_handler`
- `history_handler` -> `history_handler.lambda_handler`
- `job_status_handler` -> `job_status_handler.lambda_handler`
