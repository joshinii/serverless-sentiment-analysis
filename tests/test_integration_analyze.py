import importlib
import json
import sys
import types

import boto3


def test_analyze_handler_success_persists_to_dynamodb(monkeypatch, mock_aws_stack):
    table_name = mock_aws_stack["table_name"]

    monkeypatch.setenv("DYNAMODB_TABLE", table_name)
    monkeypatch.setenv("MODEL_VERSION", "integration-v1")

    stub_model_loader = types.ModuleType("backend.shared.model_loader")
    stub_model_loader.analyze_text = lambda text: {
        "sentiment": "POSITIVE",
        "confidence": 0.99,
        "text_preview": text[:100],
    }
    sys.modules["backend.shared.model_loader"] = stub_model_loader

    from backend.shared import config as cfg
    from backend.sentiment_analyzer import lambda_function as analyzer

    importlib.reload(cfg)
    importlib.reload(analyzer)

    analyzer.dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
    analyzer.AWS_AVAILABLE = True

    monkeypatch.setattr(
        analyzer,
        "analyze_sentiment",
        lambda text: {
            "sentiment": "POSITIVE",
            "confidence": 0.99,
            "text_preview": text[:100],
        },
    )

    event = {"body": json.dumps({"text": "Great service", "user_id": "u-123"})}
    response = analyzer.lambda_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["sentiment"] == "POSITIVE"
    assert body["model_version"] == "integration-v1"

    table = mock_aws_stack["dynamodb"].Table(table_name)
    items = table.scan()["Items"]
    assert len(items) == 1
    assert items[0]["PK"] == "USER#u-123"


def test_analyze_handler_validation_error(monkeypatch):
    stub_model_loader = types.ModuleType("backend.shared.model_loader")
    stub_model_loader.analyze_text = lambda text: {
        "sentiment": "POSITIVE",
        "confidence": 0.99,
        "text_preview": text[:100],
    }
    sys.modules["backend.shared.model_loader"] = stub_model_loader

    from backend.sentiment_analyzer import lambda_function as analyzer

    monkeypatch.setattr(
        analyzer,
        "analyze_sentiment",
        lambda text: {
            "sentiment": "POSITIVE",
            "confidence": 0.5,
            "text_preview": text,
        },
    )

    response = analyzer.lambda_handler({"body": json.dumps({"text": "   "})}, None)
    assert response["statusCode"] == 400
    assert "Text field is required" in response["body"]
