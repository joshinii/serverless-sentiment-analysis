import json
import subprocess
import os
import sys

# Paths
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
INFRA_DIR = os.path.join(ROOT_DIR, "sentiment-analysis-infrastructure")
CONFIG_FILE = os.path.join(ROOT_DIR, "deploy_config.json")

def get_terraform_outputs():
    """Run terraform output -json and return parsed dict"""
    print(f"Reading Terraform outputs from: {INFRA_DIR}")
    
    if not os.path.exists(os.path.join(INFRA_DIR, ".terraform")):
        print("Error: Terraform not initialized. Please run 'terraform init' and 'terraform apply' first.")
        sys.exit(1)

    try:
        # Run terraform output
        result = subprocess.check_output(
            ["terraform", "output", "-json"], 
            cwd=INFRA_DIR,
            stderr=subprocess.STDOUT
        )
        return json.loads(result)
    except subprocess.CalledProcessError as e:
        print(f"Error running terraform output: {e.output.decode()}")
        sys.exit(1)
    except Exception as e:
        print(f"Error parsing terraform output: {str(e)}")
        sys.exit(1)

def main():
    outputs = get_terraform_outputs()
    
    # Map Terraform outputs to config structure
    try:
        config = {
            "API_URL": outputs["api_endpoint"]["value"],
            "FRONTEND_BUCKET": outputs["frontend_bucket"]["value"],
            "DATA_BUCKET": outputs["data_bucket"]["value"],
            "CF_DIST_ID": outputs["cloudfront_distribution_id"]["value"],
            "CLOUDFRONT_URL": outputs["cloudfront_url"]["value"],
            "LAMBDAS": {
                "sentiment_analyzer": {
                    "name": outputs["lambda_functions"]["value"]["sentiment_analyzer"],
                    "path": "backend/sentiment_analyzer",
                    "handler": "lambda_function.lambda_handler",
                    "source_file": "lambda_function.py",
                    "artifact": "function.zip"
                },
                "batch_processor": {
                    "name": outputs["lambda_functions"]["value"]["batch_processor"],
                    "path": "backend/batch_processor",
                    "handler": "batch_submitter.lambda_handler",
                    "source_file": "batch_submitter.py",
                    "artifact": "function.zip"
                },
                "batch_worker": {
                    "name": outputs["lambda_functions"]["value"]["batch_worker"],
                    "path": "backend/batch_processor",
                    "handler": "batch_worker.lambda_handler",
                    "source_file": "batch_worker.py",
                    "artifact": "function.zip"
                },
                "history_handler": {
                    "name": outputs["lambda_functions"]["value"]["history_handler"],
                    "path": "backend/history",
                    "handler": "history_handler.lambda_handler",
                    "source_file": "history_handler.py",
                    "artifact": "function.zip"
                },
                "job_status_handler": {
                    "name": outputs["lambda_functions"]["value"]["job_status_handler"],
                    "path": "backend/history",
                    "handler": "job_status_handler.lambda_handler",
                    "source_file": "job_status_handler.py",
                    "artifact": "function.zip"
                }
            }
        }
        
        # Save to file
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
            
        print(f"✅ Configuration updated in {CONFIG_FILE}")
        print("You can now run 'python deploy_all.py' to deploy your code.")
        
    except KeyError as e:
        print(f"Error: Missing expected output keys in Terraform: {e}")
        print("Ensure 'outputs.tf' has all required fields.")
        sys.exit(1)

if __name__ == "__main__":
    main()
