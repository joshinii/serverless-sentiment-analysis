from pathlib import Path
import argparse
import shutil
import sys

from optimum.onnxruntime import ORTModelForSequenceClassification
from transformers import AutoTokenizer

MODEL_ID = "distilbert-base-uncased-finetuned-sst-2-english"
OUTPUT_DIR = Path("backend/model_assets")

# Adjust this list if your runtime expects different names/files.
REQUIRED_FILES = [
    "config.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
]

# Accept either tokenizer.json or vocab.txt-based tokenizer assets.
TOKENIZER_FILE_OPTIONS = [
    ["tokenizer.json"],
    ["vocab.txt"],
]

# Accept one or more ONNX naming patterns.
MODEL_FILE_OPTIONS = [
    ["model.onnx"],
    ["onnx/model.onnx"],
]


def has_any_file_set(base: Path, options: list[list[str]]) -> bool:
    for file_set in options:
        if all((base / rel_path).exists() for rel_path in file_set):
            return True
    return False


def validate_model_assets(output_dir: Path) -> tuple[bool, list[str]]:
    missing = []

    for rel_path in REQUIRED_FILES:
        if not (output_dir / rel_path).exists():
            missing.append(rel_path)

    if not has_any_file_set(output_dir, TOKENIZER_FILE_OPTIONS):
        missing.append("tokenizer.json or vocab.txt")

    if not has_any_file_set(output_dir, MODEL_FILE_OPTIONS):
        missing.append("model.onnx or onnx/model.onnx")

    return len(missing) == 0, missing


def print_validation(output_dir: Path) -> tuple[bool, list[str]]:
    """Print a per-file validation report and return (ok, missing)."""
    ok, missing = validate_model_assets(output_dir)

    all_checks = [
        *REQUIRED_FILES,
        "tokenizer.json or vocab.txt",
        "model.onnx or onnx/model.onnx",
    ]
    missing_set = set(missing)
    for label in all_checks:
        mark = "✓" if label not in missing_set else "✗"
        print(f"  {mark}  {label}")

    return ok, missing


def export_model(model_id: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Exporting {model_id} to {output_dir}...")
    model = ORTModelForSequenceClassification.from_pretrained(
        model_id,
        export=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(model_id)

    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)

    ok, missing = validate_model_assets(output_dir)
    if not ok:
        raise RuntimeError(
            f"Export finished but model assets are incomplete. Missing: {', '.join(missing)}"
        )

    print("Export complete and validated.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export or validate the ONNX sentiment model.",
        epilog=(
            "Examples:\n"
            "  python export_onnx.py              # export if assets missing\n"
            "  python export_onnx.py --force      # always re-export\n"
            "  python export_onnx.py --clean      # wipe and re-export\n"
            "  python export_onnx.py --validate   # check assets, exit 1 if invalid"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--force", action="store_true", help="Re-export even if assets already exist")
    parser.add_argument("--clean", action="store_true", help="Delete output dir before export")
    parser.add_argument("--validate", action="store_true", help="Validate assets only; do not export")
    parser.add_argument("--model-id", default=MODEL_ID, help="Hugging Face model id")
    args = parser.parse_args()

    if args.validate:
        print(f"Validating model assets in {OUTPUT_DIR}:")
        ok, missing = print_validation(OUTPUT_DIR)
        if ok:
            print("Validation passed.")
            return 0
        print(f"\nValidation FAILED. Missing: {', '.join(missing)}", file=sys.stderr)
        print("Run `python export_onnx.py` to prepare assets.", file=sys.stderr)
        return 1

    if OUTPUT_DIR.exists() and args.clean:
        shutil.rmtree(OUTPUT_DIR)

    if not args.force:
        ok, missing = validate_model_assets(OUTPUT_DIR)
        if ok:
            print(f"Model assets already present in {OUTPUT_DIR}, skipping export.")
            return 0
        else:
            print(f"Model assets missing or incomplete in {OUTPUT_DIR}: {', '.join(missing)}")
            print("Attempting export...")

    try:
        export_model(args.model_id, OUTPUT_DIR)
        print(f"\nValidating exported assets in {OUTPUT_DIR}:")
        print_validation(OUTPUT_DIR)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())