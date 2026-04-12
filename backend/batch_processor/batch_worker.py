"""
Batch Worker Lambda

Responsibilities:
- Triggered by SQS messages
- Read batch input from S3
- Reuse shared sentiment inference logic
- Update job status in DynamoDB (PROCESSING -> COMPLETED/FAILED)
- Store per-row results
"""

import csv
import json
from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
from typing import Any, Dict, List

import boto3

from backend.shared import config
from backend.shared.logger import get_logger, log_event, request_id_from_context, timer_start, latency_ms
from backend.shared.model_loader import analyze_text

logger = get_logger(__name__)

s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _update_job_status(job_id: str, status: str, extra_fields: Dict[str, Any] = None) -> None:
    table = dynamodb.Table(config.DYNAMODB_TABLE)
    now = _utc_now_iso()
    extra_fields = extra_fields or {}

    expr_names = {"#status": "status", "#updated_at": "updated_at"}
    expr_vals = {":status": status, ":updated_at": now}
    set_parts = ["#status = :status", "#updated_at = :updated_at"]

    for idx, (key, value) in enumerate(extra_fields.items()):
        name_token = f"#f{idx}"
        value_token = f":v{idx}"
        expr_names[name_token] = key
        expr_vals[value_token] = value
        set_parts.append(f"{name_token} = {value_token}")

    table.update_item(
        Key={"PK": f"JOB#{job_id}", "SK": "META"},
        UpdateExpression="SET " + ", ".join(set_parts),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_vals,
    )


def _load_rows_from_s3(bucket: str, key: str, default_user_id: str) -> List[Dict[str, Any]]:
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")

    if key.endswith(".json"):
        payload = json.loads(content)
        texts = payload.get("texts", [])
        user_id = payload.get("user_id", default_user_id)
        return [
            {
                "row": idx,
                "text": text,
                "user_id": user_id,
            }
            for idx, text in enumerate(texts)
            if isinstance(text, str) and text.strip()
        ]

    # Default to CSV format: text,user_id(optional)
    rows: List[Dict[str, Any]] = []
    reader = csv.DictReader(StringIO(content))
    for idx, item in enumerate(reader):
        text = (item.get("text") or "").strip()
        if not text:
            continue
        rows.append(
            {
                "row": idx,
                "text": text,
                "user_id": item.get("user_id", default_user_id),
            }
        )
    return rows


def _save_row_result(job_id: str, result: Dict[str, Any]) -> None:
    table = dynamodb.Table(config.DYNAMODB_TABLE)
    now_ts = int(datetime.now(timezone.utc).timestamp())
    now_iso = _utc_now_iso()

    item = {
        "PK": f"JOB#{job_id}",
        "SK": f"ROW#{str(result['row']).zfill(6)}",
        "row": result["row"],
        "user_id": result.get("user_id", "anonymous"),
        "text": result["text"],
        "sentiment": result["sentiment"],
        "confidence": Decimal(str(result["confidence"])),
        "status": result["status"],
        "model_version": config.MODEL_VERSION,
        "timestamp": now_ts,
        "created_at": now_iso,
    }
    if result.get("error"):
        item["error"] = result["error"]

    table.put_item(Item=item)


def _process_job_message(body: Dict[str, Any]) -> None:
    if not config.DYNAMODB_TABLE:
        raise ValueError("DYNAMODB_TABLE env var is required")

    job_id = body["job_id"]
    user_id = body.get("user_id", "anonymous")
    input_bucket = body["input_bucket"]
    input_key = body["input_key"]

    logger.info("Processing job_id=%s input=s3://%s/%s", job_id, input_bucket, input_key)

    _update_job_status(
        job_id,
        "PROCESSING",
        {
            "started_at": _utc_now_iso(),
            "model_version": config.MODEL_VERSION,
        },
    )

    rows = _load_rows_from_s3(input_bucket, input_key, user_id)
    if not rows:
        _update_job_status(job_id, "FAILED", {"error_message": "No valid rows found", "completed_at": _utc_now_iso()})
        raise ValueError(f"Job {job_id} has no valid rows")

    success_count = 0
    failed_count = 0

    for row in rows:
        try:
            inference = analyze_text(row["text"])
            result = {
                "row": row["row"],
                "user_id": row["user_id"],
                "text": row["text"],
                "sentiment": inference["sentiment"],
                "confidence": inference["confidence"],
                "status": "success",
            }
            success_count += 1
        except Exception as exc:
            result = {
                "row": row["row"],
                "user_id": row["user_id"],
                "text": row["text"],
                "sentiment": "ERROR",
                "confidence": 0.0,
                "status": "failed",
                "error": str(exc),
            }
            failed_count += 1

        _save_row_result(job_id, result)

    final_status = "COMPLETED" if failed_count == 0 else "FAILED"
    _update_job_status(
        job_id,
        final_status,
        {
            "processed_rows": len(rows),
            "total_rows": len(rows),
            "success_count": success_count,
            "failed_count": failed_count,
            "completed_at": _utc_now_iso(),
        },
    )

    logger.info(
        "Finished job_id=%s status=%s total=%s success=%s failed=%s",
        job_id,
        final_status,
        len(rows),
        success_count,
        failed_count,
    )


def lambda_handler(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    """
    SQS-triggered handler.

    Expected event shape:
    {
      "Records": [
        {
          "messageId": "...",
          "body": "{\"job_id\":\"...\",\"input_bucket\":\"...\",\"input_key\":\"...\"}"
        }
      ]
    }

    Returns partial batch failure response for SQS.
    """
    start_time = timer_start()
    request_id = request_id_from_context(context)
    records = event.get("Records", [])
    log_event(
        logger,
        level="INFO",
        function_name="batch_worker",
        event_type="invocation.start",
        message="Batch worker invocation started",
        request_id=request_id,
        status="start",
        latency_ms_value=0,
        extra={"record_count": len(records)},
    )

    failures = []
    for record in records:
        message_id = record.get("messageId", "unknown")
        job_id = None
        try:
            body = json.loads(record.get("body", "{}"))
            job_id = body.get("job_id")
            _process_job_message(body)
        except Exception as exc:
            log_event(
                logger,
                level="ERROR",
                function_name="batch_worker",
                event_type="record.failed",
                message="Failed to process SQS record",
                request_id=request_id,
                job_id=job_id,
                status="failed",
                latency_ms_value=latency_ms(start_time),
                extra={
                    "message_id": message_id,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            failures.append({"itemIdentifier": message_id})
    final_status = "success" if not failures else "failed"
    log_event(
        logger,
        level="INFO" if not failures else "WARNING",
        function_name="batch_worker",
        event_type="invocation.completed",
        message="Batch worker invocation completed",
        request_id=request_id,
        status=final_status,
        latency_ms_value=latency_ms(start_time),
        extra={"failed_records": len(failures), "record_count": len(records)},
    )
    return {"batchItemFailures": failures}


if __name__ == "__main__":
    # Local smoke test shape only; requires configured AWS resources to run end-to-end.
    example = {
        "Records": [
            {
                "messageId": "test-1",
                "body": json.dumps(
                    {
                        "job_id": "job-test-1",
                        "user_id": "user-1",
                        "input_bucket": "example-bucket",
                        "input_key": "jobs/job-test-1/input.json",
                    }
                ),
            }
        ]
    }
    print(lambda_handler(example))
