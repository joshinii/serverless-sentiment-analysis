import os
import boto3
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from . import config
from .logger import get_logger

logger = get_logger(__name__)

# Cached model/tokenizer
_model = None
_tokenizer = None
_use_fallback = False


def _softmax(x):
    e_x = np.exp(x - np.max(x))
    return e_x / e_x.sum(axis=0)


def _download_model_from_s3():
    if not config.MODEL_BUCKET:
        logger.warning("MODEL_BUCKET not set. Assuming local model assets.")
        return

    if not os.path.exists(config.MODEL_PATH):
        os.makedirs(config.MODEL_PATH)

    s3_client = boto3.client('s3')
    logger.info("Downloading model assets from S3")
    objects = s3_client.list_objects_v2(Bucket=config.MODEL_BUCKET, Prefix="model_assets/")
    for obj in objects.get('Contents', []):
        key = obj['Key']
        rel_path = os.path.relpath(key, "model_assets")
        if rel_path == ".":
            continue
        local_file = os.path.join(config.MODEL_PATH, rel_path)
        os.makedirs(os.path.dirname(local_file), exist_ok=True)
        s3_client.download_file(config.MODEL_BUCKET, key, local_file)


def load_model_if_needed():
    global _model, _tokenizer, _use_fallback
    if _model is not None and _tokenizer is not None:
        return

    model_file = os.path.join(config.MODEL_PATH, "model.onnx")
    tokenizer_file = os.path.join(config.MODEL_PATH, "tokenizer.json")

    if not os.path.exists(model_file) or not os.path.exists(tokenizer_file):
        try:
            _download_model_from_s3()
        except Exception as exc:
            logger.warning("Model download failed; using fallback analyzer. error=%s", str(exc))
            _use_fallback = True
            return

    if not os.path.exists(tokenizer_file) or not os.path.exists(model_file):
        logger.warning("Model assets missing locally; using fallback analyzer")
        _use_fallback = True
        return

    _tokenizer = Tokenizer.from_file(tokenizer_file)
    _tokenizer.enable_truncation(max_length=512)
    _tokenizer.enable_padding(length=512)
    _model = ort.InferenceSession(model_file)
    logger.info("ONNX model loaded")


def analyze_text(text: str):
    global _use_fallback
    load_model_if_needed()

    if _use_fallback or _model is None or _tokenizer is None:
        positive_words = ["love", "great", "good", "excellent", "amazing", "happy", "awesome"]
        negative_words = ["hate", "terrible", "bad", "worst", "awful", "horrible"]
        t = text.lower()
        pos = any(w in t for w in positive_words)
        neg = any(w in t for w in negative_words)
        if pos and not neg:
            return {"sentiment": "POSITIVE", "confidence": 0.85, "text_preview": text[:100]}
        if neg and not pos:
            return {"sentiment": "NEGATIVE", "confidence": 0.85, "text_preview": text[:100]}
        return {"sentiment": "POSITIVE", "confidence": 0.55, "text_preview": text[:100]}

    encoded = _tokenizer.encode(text)
    input_ids = np.array([encoded.ids], dtype=np.int64)
    attention_mask = np.array([encoded.attention_mask], dtype=np.int64)
    outputs = _model.run(None, {'input_ids': input_ids, 'attention_mask': attention_mask})
    logits = outputs[0][0]
    probabilities = _softmax(logits)
    sentiment_idx = int(np.argmax(probabilities))
    confidence = float(probabilities[sentiment_idx])
    labels = ["NEGATIVE", "POSITIVE"]
    return {
        "sentiment": labels[sentiment_idx],
        "confidence": confidence,
        "text_preview": text[:100],
    }
