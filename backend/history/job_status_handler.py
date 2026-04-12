"""
Job Status Lambda

GET /jobs/{id}
Returns:
- status
- progress
- result location

Data source: DynamoDB JOB#<id> / META item.
"""

import json
from decimal import Decimal
from typing import Any, Dict

import boto3

from backend.shared import config
from backend.shared.logger import get_logger, log_event, request_id_from_context, timer_start, latency_ms

logger = get_logger(__name__)

dynamodb = boto3.resource("dynamodb")


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def _extract_job_id(event: Dict[str, Any]) -> str:
    # API Gateway REST path parameter style
    params = event.get("pathParameters") or {}
    if params.get("id"):
        return params["id"]
    if params.get("job_id"):
        return params["job_id"]

    # Fallback for local/direct invocation
    if event.get("job_id"):
        return event["job_id"]

    return ""


def _build_progress(meta: Dict[str, Any]) -> Dict[str, Any]:
    total_rows = int(meta.get("total_rows", 0) or 0)
    processed_rows = int(meta.get("processed_rows", 0) or 0)
    percent = 0
    if total_rows > 0:
        percent = int((processed_rows / total_rows) * 100)

    return {
        "processed_rows": processed_rows,
        "total_rows": total_rows,
        "success_count": int(meta.get("success_count", 0) or 0),
        "failed_count": int(meta.get("failed_count", 0) or 0),
        "percent": percent,
    }


def lambda_handler(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    start_time = timer_start()
    request_id = request_id_from_context(context)
    log_event(
        logger,
        level="INFO",
        function_name="job_status_handler",
        event_type="invocation.start",
        message="Job status lookup started",
        request_id=request_id,
        status="start",
        latency_ms_value=0,
    )

    try:
        if not config.DYNAMODB_TABLE:
            log_event(
                logger,
                level="ERROR",
                function_name="job_status_handler",
                event_type="config.missing",
                message="DYNAMODB_TABLE env var is required",
                request_id=request_id,
                status="failed",
                latency_ms_value=latency_ms(start_time),
            )
            return {
                "statusCode": 500,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                },
                "body": json.dumps({"error": "DYNAMODB_TABLE env var is required"}),
            }

        job_id = _extract_job_id(event)
        if not job_id:
            log_event(
                logger,
                level="WARNING",
                function_name="job_status_handler",
                event_type="validation.failed",
                message="Job id is required",
                request_id=request_id,
                status="failed",
                latency_ms_value=latency_ms(start_time),
            )
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                },
                "body": json.dumps({"error": "job id is required in pathParameters.id"}),
            }

        table = dynamodb.Table(config.DYNAMODB_TABLE)
        response = table.get_item(Key={"PK": f"JOB#{job_id}", "SK": "META"})
        meta = response.get("Item")

        if not meta:
            log_event(
                logger,
                level="WARNING",
                function_name="job_status_handler",
                event_type="job.not_found",
                message="Job not found",
                request_id=request_id,
                job_id=job_id,
                status="failed",
                latency_ms_value=latency_ms(start_time),
            )
            return {
                "statusCode": 404,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                },
                "body": json.dumps({"error": "Job not found", "job_id": job_id}),
            }

        body = {
            "job_id": job_id,
            "status": meta.get("status", "UNKNOWN"),
            "progress": _build_progress(meta),
            "result_location": meta.get("result_location", f"dynamodb://{config.DYNAMODB_TABLE}/JOB#{job_id}"),
            "model_version": meta.get("model_version", config.MODEL_VERSION),
            "created_at": meta.get("created_at"),
            "updated_at": meta.get("updated_at"),
            "completed_at": meta.get("completed_at"),
            "error_message": meta.get("error_message"),
        }

        log_event(
            logger,
            level="INFO",
            function_name="job_status_handler",
            event_type="invocation.completed",
            message="Job status lookup completed",
            request_id=request_id,
            job_id=job_id,
            status="success",
            latency_ms_value=latency_ms(start_time),
            extra={
                "job_status": body["status"],
                "processed_rows": body["progress"].get("processed_rows", 0),
                "total_rows": body["progress"].get("total_rows", 0),
            },
        )

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(body, cls=DecimalEncoder),
        }
    except Exception as exc:
        log_event(
            logger,
            level="ERROR",
            function_name="job_status_handler",
            event_type="invocation.failed",
            message="Failed to get job status",
            request_id=request_id,
            status="failed",
            latency_ms_value=latency_ms(start_time),
            extra={
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({"error": "Failed to get job status", "message": str(exc)}),
        }


if __name__ == "__main__":
    print(
        lambda_handler(
            {
                "pathParameters": {
                    "id": "job-123",
                }
            }
        )
    )
