"""CLI entry point (Skill.md §39):

    imgmask input.png --output masked.png
    imgmask input.png --mode strict --ocr local --verify
    imgmask ./input --output ./output --recursive
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .pipeline import Pipeline

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def _iter_images(input_path: Path, recursive: bool) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    pattern = "**/*" if recursive else "*"
    return sorted(p for p in input_path.glob(pattern) if p.suffix.lower() in _IMAGE_SUFFIXES)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="imgmask", description="MaskGuard sensitive-data image redaction")
    parser.add_argument("input", help="Image file or folder")
    parser.add_argument("--output", default="./output", help="Output directory (default: ./output)")
    parser.add_argument("--config", default=None, help="Path to a config YAML overriding config.default.yaml")
    parser.add_argument("--mode", choices=["normal", "strict"], default="normal")
    parser.add_argument("--ocr", choices=["local"], default="local", help="OCR engine (only 'local' implemented)")
    parser.add_argument("--verify", action="store_true", help="Force-enable verification even if config disables it")
    parser.add_argument("--no-verify", action="store_true", help="Force-disable verification")
    parser.add_argument("--recursive", action="store_true", help="Recurse into subfolders when input is a folder")
    parser.add_argument("--rules", default=None, help="Path to a user-defined rules YAML (Skill.md §20)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    config = load_config(args.config)
    if args.mode == "strict":
        config.apply_strict_mode()
    if args.verify:
        config.masking.verification = True
    if args.no_verify:
        config.masking.verification = False

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"error: input path does not exist: {input_path}", file=sys.stderr)
        return 1

    images = _iter_images(input_path, args.recursive)
    if not images:
        print(f"error: no supported images found under {input_path}", file=sys.stderr)
        return 1

    output_root = Path(args.output)
    processed_dir = output_root / "processed"
    report_dir = output_root / "report"
    audit_log_path = output_root / "audit.log"

    pipeline = Pipeline(config, user_rules_path=args.rules)

    exit_code = 0
    for image_path in images:
        stem = image_path.stem
        output_image_path = processed_dir / f"{stem}_masked{image_path.suffix}"
        report_path = report_dir / f"{stem}_masked.json"

        result = pipeline.process(
            str(image_path),
            str(output_image_path),
            str(report_path),
            str(audit_log_path),
        )

        if result.blocked:
            exit_code = 2
            print(f"[BLOCKED] {image_path} -> verification failed under Strict Mode, output withheld")
        else:
            print(f"[OK] {image_path} -> {result.output_path} (verification: {result.verification.status})")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
