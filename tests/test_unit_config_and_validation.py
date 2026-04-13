import importlib


def test_config_defaults_and_overrides(monkeypatch):
    from backend.shared import config as cfg

    monkeypatch.setenv("MODEL_VERSION", "2.3.4")
    monkeypatch.setenv("DYNAMODB_TABLE", "table-123")
    reloaded = importlib.reload(cfg)

    assert reloaded.MODEL_VERSION == "2.3.4"
    assert reloaded.DYNAMODB_TABLE == "table-123"

    monkeypatch.delenv("DYNAMODB_TABLE", raising=False)
    reloaded = importlib.reload(cfg)
    assert reloaded.DYNAMODB_TABLE is None


def test_submitter_payload_validation():
    from backend.batch_processor import batch_submitter as submitter

    ok_inline, err_inline = submitter._validate_payload(
        {"user_id": "u1", "input_mode": "inline", "texts": ["hello", "world"]}
    )
    assert ok_inline is True
    assert err_inline == ""

    ok_s3, err_s3 = submitter._validate_payload(
        {
            "user_id": "u1",
            "input_mode": "s3",
            "s3_bucket": "bucket",
            "s3_key": "jobs/input.json",
        }
    )
    assert ok_s3 is True
    assert err_s3 == ""

    bad, bad_err = submitter._validate_payload({"input_mode": "inline", "texts": ["x"]})
    assert bad is False
    assert "user_id is required" in bad_err


def test_extract_job_id_supports_multiple_shapes():
    from backend.history import job_status_handler

    assert (
        job_status_handler._extract_job_id({"pathParameters": {"id": "job-1"}}) == "job-1"
    )
    assert (
        job_status_handler._extract_job_id({"pathParameters": {"job_id": "job-2"}})
        == "job-2"
    )
    assert job_status_handler._extract_job_id({"job_id": "job-3"}) == "job-3"
    assert job_status_handler._extract_job_id({}) == ""
