from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .errors import SegEntryError
from .gpu import build_gpu_status_payload
from .http_server import run_server
from .paths import DEFAULT_GPU_CANDIDATES
from .service import SegmentationService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standardized liver segmentation entry for local orchestration and future Orthanc integration.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    models_parser = subparsers.add_parser("models", help="List supported models and their interface status.")
    models_parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")

    gpu_parser = subparsers.add_parser("gpu-status", help="Inspect candidate GPUs and show which one auto_best would choose.")
    gpu_parser.add_argument("--gpu-candidates", default=DEFAULT_GPU_CANDIDATES)
    gpu_parser.add_argument("--gpu-min-free-memory-mb", type=int, default=4096)
    gpu_parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")

    run_parser = subparsers.add_parser("run", help="Run one standardized segmentation request.")
    run_parser.add_argument("--request-json", help="Path to a full JSON request payload.")
    run_parser.add_argument("--request-id", help="Optional request id. Auto-generated if omitted.")
    run_parser.add_argument("--input-path", help="Path to a DICOM directory or NIfTI file.")
    run_parser.add_argument("--input-type", default="auto", choices=["auto", "nifti_file", "dicom_dir"])
    run_parser.add_argument("--target", default="liver", help="Segmentation target. Current version supports liver only.")
    run_parser.add_argument("--model", default="totalsegmentator", choices=["totalsegmentator", "medsam2"])
    run_parser.add_argument("--modality", choices=["ct", "mr"], help="Required for TotalSegmentator; optional metadata for MedSAM2.")
    run_parser.add_argument("--output-dir", help="Request output directory. Defaults to seg-entry/runs/<request_id>.")
    run_parser.add_argument("--prompt-json", help="Optional prompt JSON file for prompt-based models such as MedSAM2.")
    run_parser.add_argument("--python-bin", help="Engine Python executable.")
    run_parser.add_argument("--device", default="gpu", choices=["gpu", "cpu"])
    run_parser.add_argument("--gpu-policy", default="auto_best", choices=["auto_best", "manual"])
    run_parser.add_argument("--gpu-candidates", default=DEFAULT_GPU_CANDIDATES, help="Candidate GPU pool used by auto_best.")
    run_parser.add_argument("--gpu-id", type=int, help="Explicit GPU id when gpu_policy=manual.")
    run_parser.add_argument("--gpu-min-free-memory-mb", type=int, default=4096, help="Minimum free GPU memory required for auto_best.")
    run_parser.add_argument("--cuda-visible-devices", help="Optional CUDA_VISIBLE_DEVICES value for backward compatibility.")
    run_parser.add_argument("--totalseg-home", help="Override TOTALSEG_HOME_DIR.")
    run_parser.add_argument("--totalseg-runner", help="Override TotalSegmentator liver workflow runner path.")
    run_parser.add_argument(
        "--totalseg-task-profile",
        default="core_liver",
        choices=["core_liver", "full_liver"],
        help="TotalSegmentator task profile: core_liver (liver only, faster) or full_liver (includes vessels/tumor/segments).",
    )
    run_parser.add_argument("--medsam2-repo", help="Override Medical-SAM2 repository root.")
    run_parser.add_argument("--medsam2-runner", help="Override Medical-SAM2 runner path.")
    run_parser.add_argument("--medsam2-ckpt", help="Override Medical-SAM2 checkpoint path.")
    run_parser.add_argument("--medsam2-config", help="Override Medical-SAM2 SAM config name (for example: sam2_hiera_s).")
    run_parser.add_argument("--medsam2-image-size", type=int, help="Override Medical-SAM2 internal image size.")
    run_parser.add_argument("--quiet", action="store_true", help="Reduce engine console output.")
    run_parser.add_argument("--overwrite", action="store_true", help="Overwrite existing engine outputs.")
    run_parser.add_argument("--export-mode", default="copy", choices=["copy", "symlink"])
    run_parser.add_argument("--nr-thr-resamp", type=int, default=1)
    run_parser.add_argument("--nr-thr-saving", type=int, default=1)
    run_parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")

    serve_parser = subparsers.add_parser("serve", help="Expose the standardized interface over HTTP.")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8010)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    service = SegmentationService()

    if args.command == "models":
        payload = {"models": service.describe_models()}
        print(_dump_json(payload, args.pretty))
        return 0

    if args.command == "gpu-status":
        try:
            payload = build_gpu_status_payload(
                gpu_candidates=args.gpu_candidates,
                gpu_min_free_memory_mb=args.gpu_min_free_memory_mb,
            )
            print(_dump_json(payload, args.pretty))
            return 0
        except SegEntryError as exc:
            print(_dump_json({"status": "failed", "error": exc.to_dict()}, True))
            return 1

    if args.command == "serve":
        run_server(host=args.host, port=args.port)
        return 0

    if args.command == "run":
        payload = _build_run_payload(args)
        result = service.execute(payload)
        print(_dump_json(result.response.to_dict(), args.pretty))
        return 0 if result.status_code < 400 else 1

    parser.error("Unsupported command")
    return 2


def _build_run_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.request_json:
        payload = json.loads(Path(args.request_json).read_text(encoding="utf-8"))
        return payload

    if not args.input_path:
        raise SystemExit("--input-path is required unless --request-json is provided")

    prompts = []
    if args.prompt_json:
        prompts = json.loads(Path(args.prompt_json).read_text(encoding="utf-8"))

    payload = {
        "request_id": args.request_id,
        "input_path": args.input_path,
        "input_type": args.input_type,
        "target": args.target,
        "model": args.model,
        "modality": args.modality,
        "output_dir": args.output_dir,
        "prompts": prompts,
        "engine": {
            "python_bin": args.python_bin,
            "device": args.device,
            "gpu_policy": args.gpu_policy,
            "gpu_candidates": args.gpu_candidates,
            "gpu_id": args.gpu_id,
            "gpu_min_free_memory_mb": args.gpu_min_free_memory_mb,
            "cuda_visible_devices": args.cuda_visible_devices,
            "quiet": args.quiet,
            "overwrite": args.overwrite,
            "export_mode": args.export_mode,
            "nr_thr_resamp": args.nr_thr_resamp,
            "nr_thr_saving": args.nr_thr_saving,
            "totalseg_home": args.totalseg_home,
            "totalseg_runner": args.totalseg_runner,
            "totalseg_task_profile": args.totalseg_task_profile,
            "medsam2_repo": args.medsam2_repo,
            "medsam2_runner": args.medsam2_runner,
            "medsam2_ckpt": args.medsam2_ckpt,
            "medsam2_config": args.medsam2_config,
            "medsam2_image_size": args.medsam2_image_size,
        },
    }
    return payload


def _dump_json(payload: dict[str, Any], pretty: bool) -> str:
    if pretty:
        return json.dumps(payload, indent=2, ensure_ascii=False)
    return json.dumps(payload, ensure_ascii=False)


if __name__ == "__main__":
    raise SystemExit(main())
