import logging
import json
from datetime import datetime, timezone
from time import perf_counter
from logging import StreamHandler
from logging import Formatter
from typing import Any, Dict, Optional
from . import config


def _make_formatter():
    # Structured payload is already JSON in the log message.
    fmt = '%(message)s'
    return Formatter(fmt)


def get_logger(name: str = None) -> logging.Logger:
    """Return a configured logger for Lambda handlers."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = StreamHandler()
        handler.setFormatter(_make_formatter())
        logger.addHandler(handler)
    logger.propagate = False
    logger.setLevel(config.LOG_LEVEL)
    return logger


def request_id_from_context(context: Any) -> str:
    if context and getattr(context, "aws_request_id", None):
        return str(context.aws_request_id)
    return "unknown"


def timer_start() -> float:
    return perf_counter()


def latency_ms(start_time: float) -> int:
    return int((perf_counter() - start_time) * 1000)


def log_event(
    logger: logging.Logger,
    *,
    level: str,
    function_name: str,
    event_type: str,
    message: str,
    request_id: str,
    status: str,
    latency_ms_value: int,
    job_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    payload: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level.upper(),
        "service": "sentiment-analysis",
        "function_name": function_name,
        "event_type": event_type,
        "message": message,
        "request_id": request_id,
        "job_id": job_id,
        "model_version": config.MODEL_VERSION,
        "status": status,
        "latency_ms": latency_ms_value,
    }

    if extra:
        payload.update(extra)

    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.log(log_level, json.dumps(payload, default=str))
