"""
Batch Processing Lambda Function
Processes CSV files containing multiple text samples for sentiment analysis
"""

import json
import os
import boto3
import csv
from io import StringIO
from datetime import datetime
from typing import Dict, Any, List
from decimal import Decimal

from backend.shared.logger import get_logger, log_event, request_id_from_context, timer_start, latency_ms

# Configure logging
logger = get_logger(__name__)

# AWS clients
try:
    s3_client = boto3.client('s3')
    dynamodb = boto3.resource('dynamodb')
    sns_client = boto3.client('sns')
    AWS_AVAILABLE = True
except Exception as e:
    logger.warning(f"AWS services not available: {e}")
    AWS_AVAILABLE = False
# These clients are now initialized directly, assuming they are always available in the Lambda environment


# Environment variables
MODEL_BUCKET = os.environ.get('MODEL_BUCKET', 'local-test-bucket')
DYNAMODB_TABLE = os.environ.get('DYNAMODB_TABLE', 'local-test-table')
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN', '')
MODEL_PATH = os.environ.get('MODEL_PATH', '/tmp/model_assets')

# Global variables for model
model = None
tokenizer = None

from tokenizers import Tokenizer
import onnxruntime as ort
import numpy as np



def softmax(x):
    """Compute softmax values for each sets of scores in x."""
    e_x = np.exp(x - np.max(x))
    return e_x / e_x.sum(axis=0)

def download_model_from_s3():
    """Download model assets from S3 to /tmp"""
    if not os.path.exists(MODEL_PATH):
        os.makedirs(MODEL_PATH)
    
    logger.info(f"Downloading model from s3://{MODEL_BUCKET}/model_assets ...")
    
    try:
        if not MODEL_BUCKET:
            logger.warning("MODEL_BUCKET not set. Assuming local model.")
            return

        objects = s3_client.list_objects_v2(Bucket=MODEL_BUCKET, Prefix="model_assets/")
        if 'Contents' not in objects:
            logger.error("No model assets found in S3")
            raise Exception("Model assets missing in S3")

        for obj in objects['Contents']:
            key = obj['Key']
            rel_path = os.path.relpath(key, "model_assets")
            if rel_path == ".": continue
            local_file = os.path.join(MODEL_PATH, rel_path)
            local_dir = os.path.dirname(local_file)
            if not os.path.exists(local_dir):
                os.makedirs(local_dir)
            
            logger.info(f"Downloading {key} to {local_file}")
            s3_client.download_file(MODEL_BUCKET, key, local_file)
    except Exception as e:
        logger.error(f"Failed to download model: {e}")
        raise e

def load_model():
    """Load the model"""
    global model, tokenizer
    
    if model is not None and tokenizer is not None:
        return
    
    logger.info("Loading sentiment analysis model...")
    
    try:
        # Check if model exists locally, if not download
        if not os.path.exists(os.path.join(MODEL_PATH, "model.onnx")):
            download_model_from_s3()
            
        # Load Tokenizer from tokenizer.json
        tokenizer = Tokenizer.from_file(os.path.join(MODEL_PATH, "tokenizer.json"))
        tokenizer.enable_truncation(max_length=512)
        tokenizer.enable_padding(length=512)
        
        # Load ONNX model
        model_file = os.path.join(MODEL_PATH, "model.onnx")
        model = ort.InferenceSession(model_file)
        
        logger.info("Model loaded successfully")
        
    except Exception as e:
        logger.error(f"Error loading model: {str(e)}")
        raise

def analyze_sentiment(text: str) -> Dict[str, Any]:
    """Analyze sentiment of a single text using ONNX Runtime"""
    global model, tokenizer
    
    if model is None or tokenizer is None:
        load_model()
    
    try:
        # Tokenize input text
        encoded = tokenizer.encode(text)
        
        input_ids = np.array([encoded.ids], dtype=np.int64)
        attention_mask = np.array([encoded.attention_mask], dtype=np.int64)
        
        onnx_inputs = {
            'input_ids': input_ids,
            'attention_mask': attention_mask
        }
        
        # Run inference with ONNX Runtime
        outputs = model.run(None, onnx_inputs)
        logits = outputs[0][0] # Assuming the first output is the logits
        
        # Apply softmax to get probabilities
        probabilities = softmax(logits)
        
        # Determine predicted class and confidence
        sentiment_idx = np.argmax(probabilities)
        confidence_score = float(probabilities[sentiment_idx])
        
        # Map label (0=NEGATIVE, 1=POSITIVE)
        sentiment_map = {0: "NEGATIVE", 1: "POSITIVE"}
        sentiment = sentiment_map[sentiment_idx]
        
        return {
            "sentiment": sentiment,
            "confidence": confidence_score
        }
        
    except Exception as e:
        logger.error(f"Error during inference: {str(e)}")
        return {
            "sentiment": "ERROR",
            "confidence": 0.0,
            "error": str(e)
        }


def process_csv_file(bucket: str, key: str) -> List[Dict[str, Any]]:
    """
    Download and process CSV file from S3
    
    Expected CSV format:
    text,user_id (optional)
    "I love this!",user123
    "This is bad",user456
    """
    if not AWS_AVAILABLE:
        logger.info("AWS not available - using sample data for local testing")
        return [
            {"text": "I love this!", "row": 0},
            {"text": "This is terrible", "row": 1},
            {"text": "It's okay", "row": 2}
        ]
    
    try:
        # Download CSV from S3
        response = s3_client.get_object(Bucket=bucket, Key=key)
        csv_content = response['Body'].read().decode('utf-8')
        
        # Parse CSV
        csv_reader = csv.DictReader(StringIO(csv_content))
        
        rows = []
        for i, row in enumerate(csv_reader):
            if 'text' in row:
                rows.append({
                    'text': row['text'],
                    'user_id': row.get('user_id', 'anonymous'),
                    'row': i
                })
        
        logger.info(f"Loaded {len(rows)} rows from CSV")
        return rows
        
    except Exception as e:
        logger.error(f"Error processing CSV: {str(e)}")
        raise


def save_batch_results(batch_id: str, results: List[Dict[str, Any]]) -> None:
    """Save batch processing results to DynamoDB"""
    if not AWS_AVAILABLE:
        logger.info("AWS not available - skipping DynamoDB save")
        return
    
    try:
        table_name = os.environ.get('DYNAMODB_TABLE')
        if not table_name:
            logger.error("DYNAMODB_TABLE environment variable not set - skipping save")
            return

        table = dynamodb.Table(table_name)
        timestamp = int(datetime.now().timestamp())
        
        # Save each result
        for result in results:
            item = {
                'PK': f'BATCH#{batch_id}',
                'SK': f'ROW#{str(result["row"]).zfill(6)}',
                'text': result['text'],
                'sentiment': result['sentiment'],
                'confidence': Decimal(str(result['confidence'])),
                'user_id': result.get('user_id', 'anonymous'),
                'timestamp': timestamp,
                'status': result.get('status', 'success')
            }
            
            table.put_item(Item=item)
        
        # Save batch summary
        success_count = sum(1 for r in results if r.get('status') == 'success')
        failed_count = len(results) - success_count
        
        summary = {
            'PK': f'BATCH#{batch_id}',
            'SK': 'SUMMARY',
            'total_rows': len(results),
            'success_count': success_count,
            'failed_count': failed_count,
            'status': 'COMPLETED',
            'timestamp': timestamp,
            'completed_at': datetime.now().isoformat()
        }
        
        table.put_item(Item=summary)
        
        # Link batch to user (Option A)
        # We assume all rows belong to the same user for this batch
        if results:
            user_id = results[0].get('user_id', 'anonymous')
            user_link = {
                'PK': f'USER#{user_id}',
                'SK': f'BATCH#{batch_id}',
                'batch_id': batch_id,
                'total_rows': len(results),
                'success_count': success_count,
                'failed_count': failed_count,
                'status': 'COMPLETED',
                'timestamp': timestamp,
                'created_at': datetime.now().isoformat(),
                'type': 'BATCH'
            }
            table.put_item(Item=user_link)
            logger.info(f"Linked batch {batch_id} to user {user_id}")

        logger.info(f"Saved batch results: {success_count} success, {failed_count} failed")
        
    except Exception as e:
        logger.error(f"Error saving batch results: {str(e)}")
        # Don't raise, we want to return what we have
        return


def send_completion_notification(batch_id: str, success_count: int, failed_count: int) -> None:
    """Send SNS notification when batch is complete"""
    if not AWS_AVAILABLE or not SNS_TOPIC_ARN:
        logger.info("SNS not configured - skipping notification")
        return
    
    try:
        message = f"""
Batch Processing Complete

Batch ID: {batch_id}
Total Rows: {success_count + failed_count}
Successful: {success_count}
Failed: {failed_count}
Completed At: {datetime.now().isoformat()}
        """
        
        sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f'Batch {batch_id} Processing Complete',
            Message=message
        )
        
        logger.info(f"Sent completion notification for batch {batch_id}")
        
    except Exception as e:
        logger.error(f"Error sending notification: {str(e)}")


def lambda_handler(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    """
    Lambda handler for batch processing
    
    Expected event format:
    {
        "bucket": "my-bucket",
        "key": "uploads/batch123.csv",
        "batch_id": "batch-123"
    }
    
    OR from API Gateway:
    {
        "body": "{\"bucket\": \"...\", \"key\": \"...\", \"batch_id\": \"...\"}"
    }
    """
    start_time = timer_start()
    request_id = request_id_from_context(context)
    log_event(
        logger,
        level="INFO",
        function_name="batch_handler",
        event_type="invocation.start",
        message="Batch handler invocation started",
        request_id=request_id,
        status="start",
        latency_ms_value=0,
    )
    
    try:
        # Parse request
        if 'body' in event:
            body = json.loads(event['body']) if isinstance(event['body'], str) else event['body']
        else:
            body = event
        
        bucket = body.get('bucket', MODEL_BUCKET)
        key = body.get('key', '')
        texts = body.get('texts', [])
        batch_id = body.get('batch_id', f"batch-{int(datetime.now().timestamp())}")
        
        rows = []
        if texts:
            # Process direct text input
            logger.info(f"Processing batch {batch_id} from direct input ({len(texts)} texts)")
            for i, text in enumerate(texts):
                rows.append({
                    'text': text,
                    'user_id': body.get('user_id', 'batch-user'),
                    'row': i
                })
        elif key:
            # Process CSV file from S3
            logger.info(f"Processing batch {batch_id} from s3://{bucket}/{key}")
            rows = process_csv_file(bucket, key)
        else:
            log_event(
                logger,
                level="WARNING",
                function_name="batch_handler",
                event_type="validation.failed",
                message="Batch request missing texts and key",
                request_id=request_id,
                job_id=batch_id,
                status="failed",
                latency_ms_value=latency_ms(start_time),
            )
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Either "texts" array or S3 "key" is required'})
            }
        
        if not rows:
            log_event(
                logger,
                level="WARNING",
                function_name="batch_handler",
                event_type="validation.failed",
                message="No valid rows found to process",
                request_id=request_id,
                job_id=batch_id,
                status="failed",
                latency_ms_value=latency_ms(start_time),
            )
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'No valid rows found to process'})
            }
        
        # Analyze sentiment for each row
        results = []
        for row in rows:
            try:
                sentiment_result = analyze_sentiment(row['text'])
                results.append({
                    'row': row['row'],
                    'text': row['text'],
                    'user_id': row.get('user_id', 'anonymous'),
                    'sentiment': sentiment_result['sentiment'],
                    'confidence': sentiment_result['confidence'],
                    'status': 'success'
                })
            except Exception as e:
                logger.error(f"Error processing row {row['row']}: {str(e)}")
                results.append({
                    'row': row['row'],
                    'text': row['text'],
                    'sentiment': 'ERROR',
                    'confidence': 0.0,
                    'status': 'failed',
                    'error': str(e)
                })
        
        # Save results to DynamoDB
        save_batch_results(batch_id, results)
        
        # Send notification
        success_count = sum(1 for r in results if r['status'] == 'success')
        failed_count = len(results) - success_count
        send_completion_notification(batch_id, success_count, failed_count)
        
        # Return response
        log_event(
            logger,
            level="INFO",
            function_name="batch_handler",
            event_type="invocation.completed",
            message="Batch handler invocation completed",
            request_id=request_id,
            job_id=batch_id,
            status="success",
            latency_ms_value=latency_ms(start_time),
            extra={
                "total_rows": len(results),
                "success_count": success_count,
                "failed_count": failed_count,
            },
        )
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'batch_id': batch_id,
                'total_rows': len(results),
                'success_count': success_count,
                'failed_count': failed_count,
                'status': 'COMPLETED',
                'message': f'Processed {len(results)} rows successfully'
            })
        }
        
    except Exception as e:
        log_event(
            logger,
            level="ERROR",
            function_name="batch_handler",
            event_type="invocation.failed",
            message="Batch handler invocation failed",
            request_id=request_id,
            status="failed",
            latency_ms_value=latency_ms(start_time),
            extra={
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Batch processing failed',
                'message': str(e)
            })
        }


# For local testing
if __name__ == "__main__":
    AWS_AVAILABLE = False
    print("=== Testing Batch Processing Lambda ===\n")
    
    # Test with sample data
    test_event_s3 = {
        "bucket": "test-bucket",
        "key": "test.csv",
        "batch_id": "test-batch-001"
    }
    
    test_event_text = {
        "texts": ["I love this!", "This is bad"],
        "batch_id": "test-batch-002"
    }

    print("--- Testing S3 input (EXPECT FAIL if no creds) ---")
    try:
        response = lambda_handler(test_event_s3)
        print(f"Status Code: {response['statusCode']}")
    except Exception as e:
        print(f"S3 Test Failed as expected: {e}")

    print("\n--- Testing Direct Text input ---")
    response = lambda_handler(test_event_text)
    
    print(f"Status Code: {response['statusCode']}")
    print(f"Response: {json.dumps(json.loads(response['body']), indent=2)}")
