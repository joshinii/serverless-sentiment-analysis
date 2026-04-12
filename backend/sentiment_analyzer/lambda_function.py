"""
Sentiment Analysis Lambda Function
Analyzes text sentiment using shared model loader utilities.
"""

import json
import os
import boto3
from datetime import datetime
from typing import Dict, Any
from decimal import Decimal

from backend.shared import config
from backend.shared.logger import get_logger, log_event, request_id_from_context, timer_start, latency_ms
from backend.shared.model_loader import analyze_text

logger = get_logger(__name__)

try:
    s3_client = boto3.client('s3')
    dynamodb = boto3.resource('dynamodb')
    AWS_AVAILABLE = True
except Exception:
    AWS_AVAILABLE = False

def get_secret():
    if not AWS_AVAILABLE: return None
    
    secret_name = os.environ.get('SECRET_ARN')
    region_name = os.environ.get('AWS_REGION', 'us-west-2')

    if not secret_name:
        logger.warning("SECRET_ARN not set. Skipping.")
        return None

    try:
        session = boto3.session.Session()
        client = session.client(service_name='secretsmanager', region_name=region_name)
        response = client.get_secret_value(SecretId=secret_name)
        if 'SecretString' in response:
            logger.info("Successfully retrieved runtime secret")
            return json.loads(response['SecretString'])
    except Exception as e:
        logger.error(f"Failed to retrieve secret: {e}")
        return None

# Runtime Secret Retrieval (Credential Elimination)
API_SECRETS = get_secret()


def analyze_sentiment(text):
    """Analyze sentiment using shared model loader."""
    return analyze_text(text)


def save_to_dynamodb(user_id: str, text: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Save analysis result to DynamoDB.
    Returns status dict with success/error details.
    """
    if not AWS_AVAILABLE:
        # Local testing mock
        return {"success": True, "message": "Local mode (skipped DB)"}
    
    try:
        table_name = config.DYNAMODB_TABLE
        if not table_name:
             return {"success": False, "error": "DYNAMODB_TABLE env var missing"}

        table = dynamodb.Table(table_name)
        timestamp = int(datetime.now().timestamp())
        
        item = {
            'PK': f'USER#{user_id}',
            'SK': f'ANALYSIS#{timestamp}',
            'text': text,
            'sentiment': result['sentiment'],
            'confidence': Decimal(str(result['confidence'])),
            'model_version': config.MODEL_VERSION,
            'timestamp': timestamp,
            'created_at': datetime.now().isoformat()
        }
        
        table.put_item(Item=item)
        logger.info(f"Saved result to DynamoDB for user {user_id}")
        return {"success": True}
        
    except Exception as e:
        logger.error(f"Error saving to DynamoDB: {str(e)}")
        return {"success": False, "error": str(e)}


def lambda_handler(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    """
    Lambda function handler for sentiment analysis.
    """
    start_time = timer_start()
    request_id = request_id_from_context(context)
    log_event(
        logger,
        level="INFO",
        function_name="sentiment_analyzer",
        event_type="invocation.start",
        message="Sentiment analyzer invocation started",
        request_id=request_id,
        status="start",
        latency_ms_value=0,
    )
    
    try:
        # Parse request body (from API Gateway)
        if 'body' in event:
            body = json.loads(event['body']) if isinstance(event['body'], str) else event['body']
        else:
            body = event
        
        # Extract text from request
        text = body.get('text', '')
        user_id = body.get('user_id', 'anonymous')
        
        # Validate input
        if not text or len(text.strip()) == 0:
            log_event(
                logger,
                level="WARNING",
                function_name="sentiment_analyzer",
                event_type="validation.failed",
                message="Input validation failed: text is required",
                request_id=request_id,
                status="failed",
                latency_ms_value=latency_ms(start_time),
            )
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Text field is required and cannot be empty'
                })
            }
        
        if len(text) > 5000:
            log_event(
                logger,
                level="WARNING",
                function_name="sentiment_analyzer",
                event_type="validation.failed",
                message="Input validation failed: text too long",
                request_id=request_id,
                status="failed",
                latency_ms_value=latency_ms(start_time),
                extra={"text_length": len(text)},
            )
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Text exceeds maximum length of 5000 characters'
                })
            }
        
        # Perform sentiment analysis
        result = analyze_sentiment(text)
        
        # Save to DynamoDB
        db_status = save_to_dynamodb(user_id, text, result)
        
        # Return successful response
        response_body = {
            'user_id': user_id,
            'sentiment': result['sentiment'],
            'confidence': result['confidence'],
            'model_version': config.MODEL_VERSION,
            'timestamp': int(datetime.now().timestamp()),
            'text_preview': result['text_preview'],
            'db_save_status': db_status # Debug field
        }

        log_event(
            logger,
            level="INFO",
            function_name="sentiment_analyzer",
            event_type="invocation.completed",
            message="Sentiment analyzer invocation completed",
            request_id=request_id,
            status="success",
            latency_ms_value=latency_ms(start_time),
            extra={
                "sentiment": result.get("sentiment"),
                "confidence": result.get("confidence"),
            },
        )
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(response_body)
        }
        
    except Exception as e:
        log_event(
            logger,
            level="ERROR",
            function_name="sentiment_analyzer",
            event_type="invocation.failed",
            message="Sentiment analyzer invocation failed",
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
                'error': 'Internal server error',
                'message': str(e)
            })
        }


# For local testing
if __name__ == "__main__":
    AWS_AVAILABLE = False
    print("=== Testing Sentiment Analysis Lambda ===\n")
    
    # Test cases
    test_cases = [
        {
            "text": "I absolutely love this product! It's amazing!",
            "user_id": "test-user-1"
        },
        {
            "text": "This is terrible. Worst purchase ever.",
            "user_id": "test-user-2"
        },
        {
            "text": "The product is okay, nothing special.",
            "user_id": "test-user-3"
        },
        {
            "text": "Outstanding quality and excellent customer service!",
            "user_id": "test-user-4"
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"Test Case {i}:")
        print(f"Input: {test_case['text']}")
        
        response = lambda_handler(test_case)
        
        if response['statusCode'] == 200:
            result = json.loads(response['body'])
            print(f"Sentiment: {result['sentiment']}")
            print(f"Confidence: {result['confidence']:.4f}")
        else:
            print(f"Error: {response['body']}")
        
        print("-" * 60)
