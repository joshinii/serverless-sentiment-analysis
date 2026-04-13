# Project context

This repository is a minimal production-style serverless ML inference system on AWS.

## Primary goal
Keep the product small and the infrastructure strong.

## Architecture constraints
- Prefer AWS Lambda, API Gateway, SQS, DynamoDB, S3, CloudWatch, and Terraform.
- Prefer GitHub Actions for CI/CD.
- Avoid Kubernetes, Kafka, Step Functions, MLflow, and other heavy tools unless explicitly requested.
- Keep the design resume-project sized, not enterprise-sized.

## Backend rules
- Use Python.
- Keep functions small and readable.
- Reuse shared utilities instead of duplicating logic.
- Add input validation to every API handler.
- Add model_version to responses, logs, and persisted records.
- Prefer simple modules over deep abstractions.

## Infrastructure rules
- All infrastructure changes must be made in Terraform.
- Do not rely on manual AWS console configuration when it can be codified.
- Use least-privilege IAM policies.
- Add environment variables through Terraform.

## MLOps / observability rules
- Every Lambda should emit structured JSON logs.
- Include request_id, job_id when applicable, model_version, latency, and status in logs.
- Prefer practical CloudWatch metrics and alarms over complicated observability stacks.
- Async batch processing should use SQS and a DLQ.

## CI/CD rules
- CI must run linting, tests, and terraform fmt/validate.
- Deployment should be reproducible and automated with GitHub Actions.
- Prefer dev deployment first, then optional prod approval.

## Style rules
- Prefer minimal, practical implementations.
- Do not overengineer.
- Explain tradeoffs briefly when suggesting changes.

Keep the solution minimal.
Do not introduce Kubernetes, Docker, MLflow, Step Functions, or complex release tooling.
Use Terraform + GitHub Actions + generated frontend config only.