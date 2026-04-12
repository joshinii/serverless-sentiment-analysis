import os

# Model version returned in API responses and stored with results
MODEL_VERSION = os.environ.get("MODEL_VERSION", "1.0.0")

# Paths and bucket names for model assets
MODEL_PATH = os.environ.get('MODEL_PATH', os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'model_assets'))
MODEL_BUCKET = os.environ.get('MODEL_BUCKET')

# Persistence and messaging
DYNAMODB_TABLE = os.environ.get('DYNAMODB_TABLE')
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')

# Logging
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
