import os
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "test")
    monkeypatch.setenv("MODEL_VERSION", "test-model-v1")


@pytest.fixture
def mock_aws_stack(aws_env):
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
        s3 = boto3.client("s3", region_name="us-west-2")
        sqs = boto3.client("sqs", region_name="us-west-2")

        table_name = "test-sentiment-table"
        bucket_name = "test-job-input-bucket"

        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        s3.create_bucket(
            Bucket=bucket_name,
            CreateBucketConfiguration={"LocationConstraint": "us-west-2"},
        )

        queue_url = sqs.create_queue(QueueName="batch-jobs")['QueueUrl']

        yield {
            "dynamodb": dynamodb,
            "s3": s3,
            "sqs": sqs,
            "table_name": table_name,
            "bucket_name": bucket_name,
            "queue_url": queue_url,
        }
