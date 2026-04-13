import os
import shutil
import subprocess
import sys
import zipfile
import json
import ast

# Configuration from Terraform Outputs
# Configuration from Terraform Outputs
# Configuration
CONFIG_FILE = "deploy_config.json"
REQUIRED_LAMBDAS = {
    "sentiment_analyzer",
    "batch_processor",
    "batch_worker",
    "history_handler",
    "job_status_handler",
}

def load_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILE)
    if not os.path.exists(config_path):
        print(f"Error: Configuration file '{CONFIG_FILE}' not found.")
        print("Please create it with your deployment details (API_URL, BUCKETS, etc.)")
        sys.exit(1)
    
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error parsing '{CONFIG_FILE}': {e}")
        sys.exit(1)

CONFIG = load_config()

# ... (rest of imports)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def fail_fast(message):
    print(f"Error: {message}")
    sys.exit(1)

def parse_handler(handler):
    if not isinstance(handler, str) or "." not in handler:
        fail_fast(f"Invalid handler '{handler}'. Expected format module.function")
    module, function = handler.rsplit(".", 1)
    if not module or not function:
        fail_fast(f"Invalid handler '{handler}'. Expected format module.function")
    return module, function

def assert_handler_in_source(source_file, function_name):
    try:
        with open(source_file, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=source_file)
    except SyntaxError as e:
        fail_fast(f"Syntax error in '{source_file}': {e}")

    has_function = any(
        isinstance(node, ast.FunctionDef) and node.name == function_name
        for node in tree.body
    )
    if not has_function:
        fail_fast(f"Handler function '{function_name}' not found in '{source_file}'")

def validate_lambda_config(config):
    lambdas = config.get("LAMBDAS")
    if not isinstance(lambdas, dict):
        fail_fast("'LAMBDAS' must be an object in deploy_config.json")

    missing_required = sorted(REQUIRED_LAMBDAS - set(lambdas.keys()))
    if missing_required:
        fail_fast(f"Missing required Lambda config entries: {', '.join(missing_required)}")

    for key, lambda_cfg in lambdas.items():
        for required_key in ["name", "path", "handler"]:
            if required_key not in lambda_cfg or not lambda_cfg[required_key]:
                fail_fast(f"Lambda '{key}' is missing required field '{required_key}'")

        source_path = os.path.join(BASE_DIR, lambda_cfg["path"])
        if not os.path.isdir(source_path):
            fail_fast(f"Lambda '{key}' path not found: {source_path}")

        module_name, function_name = parse_handler(lambda_cfg["handler"])
        expected_source_file = f"{module_name}.py"
        configured_source_file = lambda_cfg.get("source_file", expected_source_file)

        if configured_source_file != expected_source_file:
            fail_fast(
                f"Lambda '{key}' source_file '{configured_source_file}' must match handler module '{module_name}' ({expected_source_file})"
            )

        source_file_path = os.path.join(source_path, configured_source_file)
        if not os.path.isfile(source_file_path):
            fail_fast(f"Lambda '{key}' source file not found: {source_file_path}")

        assert_handler_in_source(source_file_path, function_name)

def copy_shared_backend_modules(package_path):
    shared_src = os.path.join(BASE_DIR, "backend", "shared")
    if not os.path.isdir(shared_src):
        fail_fast(f"Shared backend module path not found: {shared_src}")

    backend_root = os.path.join(package_path, "backend")
    shared_dst = os.path.join(backend_root, "shared")
    os.makedirs(backend_root, exist_ok=True)
    shutil.copytree(shared_src, shared_dst, dirs_exist_ok=True)

def run_command(command, cwd=None, shell=True):
    try:
        print(f"Running: {command}")
        subprocess.check_call(command, cwd=cwd, shell=shell)
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {e}")
        # sys.exit(1) # Don't exit, let the caller handle it or log it
        raise e

def zip_directory(source_dir, output_filename):
    with zipfile.ZipFile(output_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, source_dir)
                zipf.write(file_path, arcname)

def deploy_lambda(key, config):
    print(f"\n=== Deploying {key} ===")
    source_path = os.path.join(BASE_DIR, config["path"])
    package_path = os.path.join(source_path, "package")
    artifact_name = config.get("artifact", "function.zip")
    zip_path = os.path.join(source_path, artifact_name)
    module_name, _ = parse_handler(config["handler"])
    source_file = config.get("source_file", f"{module_name}.py")

    # Clean previous build
    if os.path.exists(package_path):
        shutil.rmtree(package_path)
    if os.path.exists(zip_path):
        os.remove(zip_path)
    
    os.makedirs(package_path)

    # Filter requirements to remove dev dependencies (moto, pytest)
    req_path = os.path.join(source_path, "requirements.txt")
    prod_req_path = os.path.join(source_path, "requirements_prod.txt")
    
    if os.path.exists(req_path):
        with open(req_path, 'r') as f:
            lines = f.readlines()
        
        # Filter logic
        prod_lines = [l for l in lines if not any(x in l for x in ['moto', 'pytest'])]
        
        with open(prod_req_path, 'w') as f:
            f.writelines(prod_lines)
            
        print("Installing dependencies (production)...")
        # Ensure we target manylinux for Lambda Python 3.11
        pip_cmd = [
            sys.executable, "-m", "pip", "install", 
            "-r", "requirements_prod.txt", 
            "-t", package_path,
            "--platform", "manylinux_2_17_x86_64",
            "--python-version", "3.11",
            "--implementation", "cp", 
            "--abi", "cp311",
            "--only-binary=:all:",
            "--upgrade"
        ]
        
        # Special handling for torch: ensure cpu index is respected if pip follows it
        # Actually, requirements.txt has --index-url, so it should work.

        # If it's sentiment/batch, expect large install time
        try:
             subprocess.check_call(pip_cmd, cwd=source_path)
        except subprocess.CalledProcessError as e:
            print(f"Pip install failed: {e}")
            return
            
        # Clean up temp file
        if os.path.exists(prod_req_path):
            os.remove(prod_req_path)
            
    # Copy handler code
    shutil.copy2(os.path.join(source_path, source_file), package_path)
    copy_shared_backend_modules(package_path)

    # Zip it up
    print("Creating zip package...")
    zip_directory(package_path, zip_path)

    # Check size
    zip_size = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"Zip size: {zip_size:.2f} MB")

    # Upload to S3 if > 40MB (to be safe), or always? Always is safer for large updates.
    # Use FRONTEND_BUCKET as a staging bucket or use the DATA bucket if we know it.
    # I'll use FRONTEND_BUCKET for code storage temp.
    bucket = CONFIG["FRONTEND_BUCKET"]
    s3_key = f"lambda_code/{key}/function.zip"
    
    print(f"Uploading to S3 (s3://{bucket}/{s3_key})...")
    s3_cmd = f"aws s3 cp function.zip s3://{bucket}/{s3_key}"
    try:
        run_command(s3_cmd, cwd=source_path)
        
        print(f"Updating Lambda code from S3...")
        update_cmd = f"aws lambda update-function-code --function-name {config['name']} --s3-bucket {bucket} --s3-key {s3_key}"
        run_command(update_cmd)
        print(f"✅ Successfully deployed {key}")
        
    except Exception as e:
        print(f"❌ Failed to deploy {key}: {e}")
        # Continue to next lambda
        
    # Cleanup
    # shutil.rmtree(package_path) # Optional: keep for inspection
    # os.remove(zip_path)

def upload_model_assets():
    print("\n=== Uploading Model Assets to S3 ===")
    model_assets_src = os.path.join(BASE_DIR, "backend", "model_assets")
    bucket = CONFIG["DATA_BUCKET"]
    
    if not os.path.exists(model_assets_src):
        print("Warning: backend/model_assets not found. Skipping model upload.")
        return

    # Check if model.onnx exists
    if not os.path.exists(os.path.join(model_assets_src, "model.onnx")):
        print("Warning: model.onnx not found. Skipping.")
        return
        
    print(f"Syncing model assets to s3://{bucket}/model_assets/ ...")
    cmd = f"aws s3 sync . s3://{bucket}/model_assets/"
    try:
        run_command(cmd, cwd=model_assets_src)
        print("✅ Model assets uploaded successfully")
    except Exception as e:
        print(f"❌ Failed to upload model assets: {e}")

def update_frontend():
    print("\n=== Updating Frontend ===")
    config_js_path = os.path.join(BASE_DIR, "frontend", "config.js")

    config_js = (
        "// Generated by deploy_all.py\n"
        "window.APP_CONFIG = window.APP_CONFIG || {};\n"
        f"window.APP_CONFIG.API_BASE_URL = \"{CONFIG['API_URL']}\";\n"
    )

    with open(config_js_path, 'w', encoding='utf-8') as f:
        f.write(config_js)

    print(f"Generated frontend/config.js with API_BASE_URL={CONFIG['API_URL']}")

def deploy_frontend():
    print("\n=== Deploying Frontend to S3 ===")
    frontend_dir = os.path.join(BASE_DIR, "frontend")
    
    # Upload static frontend files
    cmd = f"aws s3 cp index.html s3://{CONFIG['FRONTEND_BUCKET']}/"
    try:
        run_command(cmd, cwd=frontend_dir)
        run_command(f"aws s3 cp config.js s3://{CONFIG['FRONTEND_BUCKET']}/", cwd=frontend_dir)
        run_command(f"aws s3 cp styles.css s3://{CONFIG['FRONTEND_BUCKET']}/", cwd=frontend_dir)
    except Exception as e:
        print(f"❌ Failed to deploy frontend: {e}")

def invalidate_cache():
    print("\n=== Invalidating CloudFront Cache ===")
    cmd = f"aws cloudfront create-invalidation --distribution-id {CONFIG['CF_DIST_ID']} --paths \"/*\""
    try:
        run_command(cmd)
    except Exception as e:
        print(f"❌ Failed to invalidate cache: {e}")

def main():
    print("Starting Automated Deployment...")
    validate_lambda_config(CONFIG)
    
    # 1. Update Frontend Code
    update_frontend()
    
    # 2. Upload Model Assets
    upload_model_assets()

    # 3. Deploy Lambdas
    for key, lambda_config in CONFIG["LAMBDAS"].items():
        deploy_lambda(key, lambda_config)
        
    # 3. Deploy Frontend
    deploy_frontend()
    
    # 4. Invalidate Cache
    invalidate_cache()
    
    print("\n✅ Deployment Complete!")
    print(f"Access your app at: {CONFIG['CLOUDFRONT_URL']}")
    print("Don't forget to confirm your SNS email subscription!")

if __name__ == "__main__":
    main()
