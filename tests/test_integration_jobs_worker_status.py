import importlib
import json
import sys
import types

import boto3
from boto3.dynamodb.conditions import Key


def test_jobs_submit_worker_and_status_flow(monkeypatch, mock_aws_stack):
    table_name = mock_aws_stack["table_name"]
    bucket_name = mock_aws_stack["bucket_name"]
    queue_url = mock_aws_stack["queue_url"]

    monkeypatch.setenv("DYNAMODB_TABLE", table_name)
    monkeypatch.setenv("JOB_INPUT_BUCKET", bucket_name)
    monkeypatch.setenv("JOB_QUEUE_URL", queue_url)
    monkeypatch.setenv("MODEL_VERSION", "integration-v1")

    stub_model_loader = types.ModuleType("backend.shared.model_loader")
    stub_model_loader.analyze_text = lambda text: {
        "sentiment": "POSITIVE" if "good" in text else "NEGATIVE",
        "confidence": 0.9,
        "text_preview": text[:100],
    }
    sys.modules["backend.shared.model_loader"] = stub_model_loader

    from backend.shared import config as cfg
    from backend.batch_processor import batch_submitter
    from backend.batch_processor import batch_worker
    from backend.history import job_status_handler

    importlib.reload(cfg)
    importlib.reload(batch_submitter)
    importlib.reload(batch_worker)
    importlib.reload(job_status_handler)

    batch_submitter.JOB_INPUT_BUCKET = bucket_name
    batch_submitter.JOB_QUEUE_URL = queue_url

    batch_worker.dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
    batch_worker.s3_client = boto3.client("s3", region_name="us-west-2")

    job_status_handler.dynamodb = boto3.resource("dynamodb", region_name="us-west-2")

    monkeypatch.setattr(batch_worker, "analyze_text", stub_model_loader.analyze_text)

    submit_event = {
        "body": json.dumps(
            {
                "user_id": "worker-user",
                "input_mode": "inline",
                "texts": ["good item", "bad item"],
            }
        )
    }

    submit_response = batch_submitter.lambda_handler(submit_event, None)
    assert submit_response["statusCode"] == 202
    submit_body = json.loads(submit_response["body"])
    job_id = submit_body["job_id"]

    sqs = mock_aws_stack["sqs"]
    received = sqs.receive_message(
        QueueUrl=queue_url,
        MessageAttributeNames=["All"],
        MaxNumberOfMessages=1,
        WaitTimeSeconds=1,
    )
    assert "Messages" in received

    message = received["Messages"][0]
    worker_event = {
        "Records": [
            {
                "messageId": message["MessageId"],
                "body": message["Body"],
            }
        ]
    }

    worker_response = batch_worker.lambda_handler(worker_event, None)
    assert worker_response == {"batchItemFailures": []}

    status_response = job_status_handler.lambda_handler(
        {"pathParameters": {"id": job_id}},
        None,
    )
    assert status_response["statusCode"] == 200

    status_body = json.loads(status_response["body"])
    assert status_body["job_id"] == job_id
    assert status_body["status"] in {"COMPLETED", "FAILED"}
    assert status_body["progress"]["total_rows"] == 2
    assert status_body["progress"]["processed_rows"] == 2

    table = mock_aws_stack["dynamodb"].Table(table_name)
    rows = table.query(
        KeyConditionExpression=Key("PK").eq(f"JOB#{job_id}")
    )["Items"]
    assert any(item["SK"] == "META" for item in rows)
    assert any(item["SK"].startswith("ROW#") for item in rows)
