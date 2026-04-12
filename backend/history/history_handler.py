"""
History Retrieval Lambda Function
Retrieves user's sentiment analysis history from DynamoDB
"""

import json
import os
import boto3
from typing import Dict, Any, List
from decimal import Decimal
from boto3.dynamodb.conditions import Key

from backend.shared.logger import get_logger, log_event, request_id_from_context, timer_start, latency_ms

# Configure logging
logger = get_logger(__name__)

# AWS clients
try:
    dynamodb = boto3.resource('dynamodb')
    AWS_AVAILABLE = True
except Exception as e:
    logger.warning(f"AWS services not available: {e}")
    AWS_AVAILABLE = False

# Environment variables
DYNAMODB_TABLE = os.environ.get('DYNAMODB_TABLE', 'local-test-table')


class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert Decimal to float for JSON serialization"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def get_user_history(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Retrieve user's analysis history from DynamoDB
    
    Args:
        user_id: User identifier
        limit: Maximum number of results to return
        
    Returns:
        List of analysis results
    """
    if not AWS_AVAILABLE:
        logger.info("AWS not available - returning sample data for local testing")
        return [
            {
                "text": "I love this product!",
                "sentiment": "POSITIVE",
                "confidence": 0.9987,
                "timestamp": 1699900000,
                "created_at": "2024-11-13T10:00:00"
            },
            {
                "text": "This is terrible",
                "sentiment": "NEGATIVE",
                "confidence": 0.9876,
                "timestamp": 1699900060,
                "created_at": "2024-11-13T10:01:00"
            },
            {
                "text": "It's okay",
                "sentiment": "POSITIVE",
                "confidence": 0.5123,
                "timestamp": 1699900120,
                "created_at": "2024-11-13T10:02:00"
            }
        ]
    
    try:
        table_name = os.environ.get('DYNAMODB_TABLE')
        if not table_name:
            logger.error("DYNAMODB_TABLE environment variable not set")
            # Fallback for now to see if that's the issue, or fail loud
             # Returning empty with error log
            return []

        table = dynamodb.Table(table_name)
        
        logger.info(f"Querying table {table_name} for user {user_id}")
        
        # Query user's analysis history (and batch history)
        # We remove the SK condition to get all user items (ANALYSIS# and BATCH#)
        response = table.query(
            KeyConditionExpression=Key('PK').eq(f'USER#{user_id}'),
            Limit=limit,
            ScanIndexForward=False  # Most recent first
        )
        
        items = response.get('Items', [])
        logger.info(f"Found {len(items)} items for user {user_id}")
        
        # Format results
        results = []
        for item in items:
            sk = item.get('SK', '')
            if sk.startswith('BATCH#'):
                results.append({
                    'type': 'BATCH',
                    'batch_id': item.get('batch_id', ''),
                    'text': f"Batch Processing ({item.get('total_rows', 0)} items)",
                    'sentiment': item.get('status', 'UNKNOWN'),
                    'confidence': 1.0 if item.get('status') == 'COMPLETED' else 0.0,
                    'timestamp': item.get('timestamp', 0),
                    'created_at': item.get('created_at', ''),
                    'summary': f"Success: {item.get('success_count', 0)}, Failed: {item.get('failed_count', 0)}"
                })
            else:
                results.append({
                    'type': 'ANALYSIS',
                    'text': item.get('text', ''),
                    'sentiment': item.get('sentiment', ''),
                    'confidence': float(item.get('confidence', 0.0)),
                    'timestamp': item.get('timestamp', 0),
                    'created_at': item.get('created_at', '')
                })
        
        return results
        
    except Exception as e:
        logger.error(f"Error retrieving history: {str(e)}")
        raise


def get_batch_results(batch_id: str) -> Dict[str, Any]:
    """
    Retrieve batch processing results
    
    Args:
        batch_id: Batch identifier
        
    Returns:
        Dictionary with batch summary and results
    """
    if not AWS_AVAILABLE:
        logger.info("AWS not available - returning sample data for local testing")
        return {
            "batch_id": batch_id,
            "status": "COMPLETED",
            "total_rows": 100,
            "success_count": 98,
            "failed_count": 2,
            "results": [
                {"row": 0, "text": "Sample 1", "sentiment": "POSITIVE", "confidence": 0.95},
                {"row": 1, "text": "Sample 2", "sentiment": "NEGATIVE", "confidence": 0.87}
            ]
        }
    
    try:
        table = dynamodb.Table(DYNAMODB_TABLE)
        
        # Get batch summary
        summary_response = table.get_item(
            Key={
                'PK': f'BATCH#{batch_id}',
                'SK': 'SUMMARY'
            }
        )
        
        summary = summary_response.get('Item', {})
        
        if not summary:
            return {
                'error': 'Batch not found',
                'batch_id': batch_id
            }
        
        # Get batch results
        results_response = table.query(
            KeyConditionExpression=Key('PK').eq(f'BATCH#{batch_id}') & Key('SK').begins_with('ROW#'),
            Limit=1000  # Adjust based on expected batch size
        )
        
        results = []
        for item in results_response.get('Items', []):
            results.append({
                'row': int(item['SK'].split('#')[1]),
                'text': item.get('text', ''),
                'sentiment': item.get('sentiment', ''),
                'confidence': float(item.get('confidence', 0.0)),
                'status': item.get('status', 'unknown')
            })
        
        # Sort by row number
        results.sort(key=lambda x: x['row'])
        
        return {
            'batch_id': batch_id,
            'status': summary.get('status', 'UNKNOWN'),
            'total_rows': int(summary.get('total_rows', 0)),
            'success_count': int(summary.get('success_count', 0)),
            'failed_count': int(summary.get('failed_count', 0)),
            'completed_at': summary.get('completed_at', ''),
            'results': results
        }
        
    except Exception as e:
        logger.error(f"Error retrieving batch results: {str(e)}")
        raise


def lambda_handler(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    """
    Lambda handler for history retrieval
    
    Expected event format (API Gateway):
    {
        "queryStringParameters": {
            "user_id": "user123",
            "limit": "50"
        }
    }
    
    OR for batch results:
    {
        "queryStringParameters": {
            "batch_id": "batch-123"
        }
    }
    """
    start_time = timer_start()
    request_id = request_id_from_context(context)
    log_event(
        logger,
        level="INFO",
        function_name="history_handler",
        event_type="invocation.start",
        message="History handler invocation started",
        request_id=request_id,
        status="start",
        latency_ms_value=0,
    )
    
    try:
        # Parse query parameters
        params = event.get('queryStringParameters', {}) or {}
        
        user_id = params.get('user_id')
        batch_id = params.get('batch_id')
        limit = int(params.get('limit', 50))
        
        # Validate limit
        if limit > 1000:
            limit = 1000
        if limit < 1:
            limit = 10
        
        # Determine what to retrieve
        if batch_id:
            # Retrieve batch results
            results = get_batch_results(batch_id)
            log_event(
                logger,
                level="INFO",
                function_name="history_handler",
                event_type="invocation.completed",
                message="History handler invocation completed",
                request_id=request_id,
                job_id=batch_id,
                status="success",
                latency_ms_value=latency_ms(start_time),
                extra={"lookup_type": "batch"},
            )
            
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps(results, cls=DecimalEncoder)
            }
            
        elif user_id:
            # Retrieve user history
            history = get_user_history(user_id, limit)
            log_event(
                logger,
                level="INFO",
                function_name="history_handler",
                event_type="invocation.completed",
                message="History handler invocation completed",
                request_id=request_id,
                status="success",
                latency_ms_value=latency_ms(start_time),
                extra={"lookup_type": "user", "user_id": user_id, "limit": limit, "count": len(history)},
            )
            
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'user_id': user_id,
                    'count': len(history),
                    'history': history
                }, cls=DecimalEncoder)
            }
            
        else:
            log_event(
                logger,
                level="WARNING",
                function_name="history_handler",
                event_type="validation.failed",
                message="Either user_id or batch_id is required",
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
                    'error': 'Either user_id or batch_id parameter is required'
                })
            }

    except Exception as e:
        log_event(
            logger,
            level="ERROR",
            function_name="history_handler",
            event_type="invocation.failed",
            message="History retrieval failed",
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
                'error': 'Failed to retrieve history',
                'message': str(e)
            })
        }


# For local testing
if __name__ == "__main__":
    AWS_AVAILABLE = False
    print("=== Testing History Lambda ===\n")
    
    # Test 1: Get user history
    print("Test 1: Get user history")
    test_event_1 = {
        "queryStringParameters": {
            "user_id": "test-user-123",
            "limit": "10"
        }
    }
    
    response_1 = lambda_handler(test_event_1)
    print(f"Status: {response_1['statusCode']}")
    print(f"Response: {json.dumps(json.loads(response_1['body']), indent=2)}")
    print("-" * 60)
    
    # Test 2: Get batch results
    print("\nTest 2: Get batch results")
    test_event_2 = {
        "queryStringParameters": {
            "batch_id": "batch-001"
        }
    }
    
    response_2 = lambda_handler(test_event_2)
    print(f"Status: {response_2['statusCode']}")
    print(f"Response: {json.dumps(json.loads(response_2['body']), indent=2)}")
    print("-" * 60)
    
    # Test 3: Missing parameters
    print("\nTest 3: Missing parameters (should fail)")
    test_event_3 = {
        "queryStringParameters": {}
    }
    
    response_3 = lambda_handler(test_event_3)
    print(f"Status: {response_3['statusCode']}")
    print(f"Response: {json.dumps(json.loads(response_3['body']), indent=2)}")
