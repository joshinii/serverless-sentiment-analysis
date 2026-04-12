"""
Batch Job Submitter Lambda

Responsibilities:
- Create a job_id
- Store job metadata in DynamoDB
- Upload inline input payload to S3 when needed
- Send a job message to SQS
- Return job_id to caller
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import boto3

from backend.shared import config
from backend.shared.logger import get_logger, log_event, request_id_from_context, timer_start, latency_ms

logger = get_logger(__name__)


# Environment
JOB_QUEUE_URL = os.environ.get("JOB_QUEUE_URL", "")
JOB_INPUT_BUCKET = os.environ.get("JOB_INPUT_BUCKET", "")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _create_job_id() -> str:
    ts = int(datetime.now(timezone.utc).timestamp())
    suffix = uuid.uuid4().hex[:8]
    return f"job-{ts}-{suffix}"


def _parse_event(event: Dict[str, Any]) -> Dict[str, Any]:
    if "body" in event:
        body = event["body"]
        if isinstance(body, str):
            return json.loads(body)
        return body or {}
    return event or {}


def _validate_payload(payload: Dict[str, Any]) -> Tuple[bool, str]:
    user_id = payload.get("user_id")
    input_mode = payload.get("input_mode", "inline")

    if not user_id:
        return False, "user_id is required"

    if input_mode not in {"inline", "s3"}:
        return False, "input_mode must be one of: inline, s3"

    if input_mode == "inline":
        texts = payload.get("texts")
        if not isinstance(texts, list) or not texts:
            return False, "texts must be a non-empty array when input_mode=inline"
        if not all(isinstance(t, str) and t.strip() for t in texts):
            return False, "all texts entries must be non-empty strings"

    if input_mode == "s3":
        if not payload.get("s3_bucket") or not payload.get("s3_key"):
            return False, "s3_bucket and s3_key are required when input_mode=s3"

    return True, ""


def _put_job_metadata(
    dynamodb_resource: Any,
    table_name: str,
    job_id: str,
    user_id: str,
    input_bucket: str,
    input_key: str,
    total_rows: int,
    submitted_at: str,
) -> None:
    table = dynamodb_resource.Table(table_name)
    result_location = f"dynamodb://{table_name}/JOB#{job_id}"

    job_item = {
        "PK": f"JOB#{job_id}",
        "SK": "META",
        "job_id": job_id,
        "user_id": user_id,
        "status": "QUEUED",
        "input_bucket": input_bucket,
        "input_key": input_key,
        "total_rows": total_rows,
        "processed_rows": 0,
        "success_count": 0,
        "failed_count": 0,
        "result_location": result_location,
        "model_version": config.MODEL_VERSION,
        "created_at": submitted_at,
        "updated_at": submitted_at,
        "type": "JOB",
    }
    table.put_item(Item=job_item)

    # Link job to user for history-style lookups
    user_link_item = {
        "PK": f"USER#{user_id}",
        "SK": f"JOB#{job_id}",
        "job_id": job_id,
        "status": "QUEUED",
        "total_rows": total_rows,
        "result_location": result_location,
        "model_version": config.MODEL_VERSION,
        "created_at": submitted_at,
        "type": "JOB",
    }
    table.put_item(Item=user_link_item)


def _upload_inline_input(
    s3_client: Any,
    bucket: str,
    job_id: str,
    user_id: str,
    texts: List[str],
) -> str:
    key = f"jobs/{job_id}/input.json"
    body = {
        "job_id": job_id,
        "user_id": user_id,
        "texts": texts,
        "model_version": config.MODEL_VERSION,
        "submitted_at": _utc_now_iso(),
    }
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(body).encode("utf-8"),
        ContentType="application/json",
    )
    return key


def _send_job_message(
    sqs_client: Any,
    queue_url: str,
    job_id: str,
    user_id: str,
    input_bucket: str,
    input_key: str,
    total_rows: int,
    submitted_at: str,
) -> None:
    message_body = {
        "job_id": job_id,
        "user_id": user_id,
        "input_bucket": input_bucket,
        "input_key": input_key,
        "total_rows": total_rows,
        "submitted_at": submitted_at,
        "model_version": config.MODEL_VERSION,
    }

    sqs_client.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(message_body),
        MessageAttributes={
            "event_type": {
                "StringValue": "job.submitted",
                "DataType": "String",
            },
            "model_version": {
                "StringValue": config.MODEL_VERSION,
                "DataType": "String",
            },
        },
    )


def lambda_handler(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    start_time = timer_start()
    request_id = request_id_from_context(context)
    log_event(
        logger,
        level="INFO",
        function_name="batch_submitter",
        event_type="invocation.start",
        message="Batch job submission started",
        request_id=request_id,
        status="start",
        latency_ms_value=0,
    )

    try:
        payload = _parse_event(event)
        valid, error = _validate_payload(payload)
        if not valid:
            log_event(
                logger,
                level="WARNING",
                function_name="batch_submitter",
                event_type="validation.failed",
                message="Batch submit payload validation failed",
                request_id=request_id,
                status="failed",
                latency_ms_value=latency_ms(start_time),
                extra={"error_message": error},
            )
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                },
                "body": json.dumps({"error": error}),
            }

        if not config.DYNAMODB_TABLE:
            log_event(
                logger,
                level="ERROR",
                function_name="batch_submitter",
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

        if not JOB_QUEUE_URL:
            log_event(
                logger,
                level="ERROR",
                function_name="batch_submitter",
                event_type="config.missing",
                message="JOB_QUEUE_URL env var is required",
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
                "body": json.dumps({"error": "JOB_QUEUE_URL env var is required"}),
            }

        job_id = _create_job_id()
        submitted_at = _utc_now_iso()

        user_id = payload["user_id"]
        input_mode = payload.get("input_mode", "inline")
        total_rows = len(payload.get("texts", [])) if input_mode == "inline" else int(payload.get("total_rows", 0))

        s3_client = boto3.client("s3")
        sqs_client = boto3.client("sqs")
        dynamodb_resource = boto3.resource("dynamodb")

        if input_mode == "inline":
            input_bucket = payload.get("s3_bucket") or JOB_INPUT_BUCKET
            if not input_bucket:
                log_event(
                    logger,
                    level="ERROR",
                    function_name="batch_submitter",
                    event_type="config.missing",
                    message="JOB_INPUT_BUCKET env var (or s3_bucket in request) is required for inline mode",
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
                    "body": json.dumps({"error": "JOB_INPUT_BUCKET env var (or s3_bucket in request) is required for inline mode"}),
                }

            input_key = _upload_inline_input(
                s3_client=s3_client,
                bucket=input_bucket,
                job_id=job_id,
                user_id=user_id,
                texts=payload["texts"],
            )
        else:
            input_bucket = payload["s3_bucket"]
            input_key = payload["s3_key"]

        _put_job_metadata(
            dynamodb_resource=dynamodb_resource,
            table_name=config.DYNAMODB_TABLE,
            job_id=job_id,
            user_id=user_id,
            input_bucket=input_bucket,
            input_key=input_key,
            total_rows=total_rows,
            submitted_at=submitted_at,
        )

        _send_job_message(
            sqs_client=sqs_client,
            queue_url=JOB_QUEUE_URL,
            job_id=job_id,
            user_id=user_id,
            input_bucket=input_bucket,
            input_key=input_key,
            total_rows=total_rows,
            submitted_at=submitted_at,
        )

        log_event(
            logger,
            level="INFO",
            function_name="batch_submitter",
            event_type="job.submitted",
            message="Batch job queued successfully",
            request_id=request_id,
            job_id=job_id,
            status="success",
            latency_ms_value=latency_ms(start_time),
            extra={"user_id": user_id, "total_rows": total_rows},
        )
        return {
            "statusCode": 202,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(
                {
                    "job_id": job_id,
                    "status": "QUEUED",
                    "model_version": config.MODEL_VERSION,
                    "submitted_at": submitted_at,
                }
            ),
        }

    except Exception as exc:
        log_event(
            logger,
            level="ERROR",
            function_name="batch_submitter",
            event_type="invocation.failed",
            message="Batch job submission failed",
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
            "body": json.dumps({"error": "Job submission failed", "message": str(exc)}),
        }


if __name__ == "__main__":
    # Local smoke test for request validation and response shape.
    test_event = {
        "body": json.dumps(
            {
                "user_id": "test-user",
                "input_mode": "inline",
                "texts": ["I love this", "This is bad"],
            }
        )
    }
    print(lambda_handler(test_event))
