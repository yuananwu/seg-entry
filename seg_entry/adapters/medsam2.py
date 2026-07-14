from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from ..contracts import Artifact, SegmentationRequest
from ..errors import SegEntryError
from ..gpu import select_gpu
from ..inputs import sanitize_name
from ..paths import (
    MEDICAL_SAM2_REPO,
    MEDICAL_SAM2_RUNNER,
    MEDSAM2_REPO,
    MEDSAM2_RUNNER,
    default_medsam2_python,
)
from .base import (
    AdapterResult,
    MODEL_STANDARD_VERSION,
    ModelCapability,
    RunContext,
    SEGMENTATION_OUTPUT_FORMAT,
    SIDECAR_FORMATS,
    SegmentationAdapter,
)


SUPPORTED_PROMPT_KINDS = {"bbox_2d", "points_2d", "diameter_line_2d"}
LEGACY_RUNNER_ALIAS = "medical_sam2_legacy"
COMPAT_RUNNER_ALIAS = "medsam2_compat"

LEGACY_DEFAULT_CONFIG = "sam2_hiera_s"
LEGACY_DEFAULT_IMAGE_SIZE = 1024
LEGACY_DEFAULT_CKPT = MEDICAL_SAM2_REPO / "checkpoints" / "sam2_hiera_small.pt"

COMPAT_DEFAULT_CONFIG = "configs/sam2.1_hiera_t512.yaml"
COMPAT_DEFAULT_IMAGE_SIZE = 512
COMPAT_DEFAULT_CKPT = MEDSAM2_REPO / "checkpoints" / "MedSAM2_latest.pt"

LEGACY_CONFIG_ALIASES = {"sam2_hiera_t", "sam2_hiera_s", "sam2_hiera_b+", "sam2_hiera_l"}
COMPAT_CONFIG_ALIASES = {
    "sam2.1_hiera_t512",
    "sam2.1_hiera_t512.yaml",
    "configs/sam2.1_hiera_t512.yaml",
    "configs/sam2.1/sam2.1_hiera_t512.yaml",
}


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _runner_selector_kind(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip().lower()
    if text == LEGACY_RUNNER_ALIAS:
        return LEGACY_RUNNER_ALIAS
    if text == COMPAT_RUNNER_ALIAS:
        return COMPAT_RUNNER_ALIAS
    return None


def _is_medsam2_release_checkpoint(path: Path | None) -> bool:
    if path is None:
        return False
    return path.name.startswith("MedSAM2_") and path.suffix == ".pt"


def _normalize_compat_config(value: str | None) -> str:
    if not value:
        return COMPAT_DEFAULT_CONFIG

    text = value.strip().replace("\\", "/")
    basename = Path(text).name
    stem = Path(basename).stem
    if text in COMPAT_CONFIG_ALIASES or basename in COMPAT_CONFIG_ALIASES or stem in COMPAT_CONFIG_ALIASES:
        return COMPAT_DEFAULT_CONFIG
    if text in LEGACY_CONFIG_ALIASES or stem in LEGACY_CONFIG_ALIASES:
        return COMPAT_DEFAULT_CONFIG
    return text


def _normalize_legacy_config(value: str | None) -> str:
    text = (value or "").strip()
    return text or LEGACY_DEFAULT_CONFIG


class MedSam2Adapter(SegmentationAdapter):
    capability = ModelCapability(
        name="medsam2",
        status="pilot",
        targets=("liver",),
        input_types=("nifti_file", "dicom_dir"),
        supported_modalities=("ct", "mr"),
        prompt_required=True,
        prompt_kinds=("bbox_2d", "points_2d", "diameter_line_2d"),
        service_contract_version=MODEL_STANDARD_VERSION,
        segmentation_output_format=SEGMENTATION_OUTPUT_FORMAT,
        sidecar_formats=SIDECAR_FORMATS + ("png",),
        notes="Runs prompt-driven liver lesion segmentation via the legacy Medical-SAM2 workflow or the MedSAM2-compatible workflow, depending on the requested runner/checkpoint.",
    )

    def validate_request(self, request: SegmentationRequest) -> None:
        if request.target != "liver":
            raise SegEntryError(
                "MedSAM2 adapter currently supports target='liver' only.",
                code="unsupported_target",
                status=400,
            )

        if request.input_type not in {"nifti_file", "dicom_dir"}:
            raise SegEntryError(
                "MedSAM2 input_type must be 'nifti_file' or 'dicom_dir'.",
                code="invalid_input_type",
                status=400,
            )

        if not request.prompts:
            raise SegEntryError(
                "MedSAM2 requires prompts. Provide bbox_2d, points_2d, or diameter_line_2d prompts.",
                code="prompt_required",
                status=400,
            )

        for prompt in request.prompts:
            prompt_kind = prompt.kind.lower()
            if prompt_kind not in SUPPORTED_PROMPT_KINDS:
                raise SegEntryError(
                    f"Unsupported MedSAM2 prompt kind: {prompt.kind}",
                    code="unsupported_prompt_kind",
                    status=400,
                    details={"supported": sorted(SUPPORTED_PROMPT_KINDS)},
                )

            if prompt_kind == "bbox_2d":
                if not prompt.bbox or len(prompt.bbox) != 4:
                    raise SegEntryError(
                        "bbox_2d prompt must include bbox=[x0,y0,x1,y1].",
                        code="invalid_prompt_bbox",
                        status=400,
                    )
            else:
                if not prompt.points:
                    raise SegEntryError(
                        f"{prompt_kind} prompt must include non-empty points.",
                        code="invalid_prompt_points",
                        status=400,
                    )

        if request.engine.device != "gpu":
            raise SegEntryError(
                "MedSAM2 workflow currently supports device='gpu' only.",
                code="invalid_device",
                status=400,
            )

        if request.engine.export_mode not in {"copy", "symlink"}:
            raise SegEntryError(
                "MedSAM2 export_mode must be 'copy' or 'symlink'.",
                code="invalid_export_mode",
                status=400,
            )

    def run(self, request: SegmentationRequest, context: RunContext) -> AdapterResult:
        self.validate_request(request)

        explicit_runner_selector = _runner_selector_kind(request.engine.medsam2_runner)
        explicit_runner_path = None
        if request.engine.medsam2_runner and explicit_runner_selector is None:
            explicit_runner_path = Path(request.engine.medsam2_runner).expanduser().resolve()

        explicit_repo_root = None
        if request.engine.medsam2_repo:
            explicit_repo_root = Path(request.engine.medsam2_repo).expanduser().resolve()

        requested_ckpt = None
        if request.engine.medsam2_ckpt:
            requested_ckpt = Path(request.engine.medsam2_ckpt).expanduser().resolve()

        use_compat_runner = False
        if explicit_runner_selector == COMPAT_RUNNER_ALIAS:
            use_compat_runner = True
        elif explicit_runner_selector == LEGACY_RUNNER_ALIAS:
            use_compat_runner = False
        elif explicit_runner_path is not None:
            if explicit_runner_path == MEDSAM2_RUNNER or _path_is_within(explicit_runner_path, MEDSAM2_REPO):
                use_compat_runner = True
            elif explicit_runner_path == MEDICAL_SAM2_RUNNER or _path_is_within(explicit_runner_path, MEDICAL_SAM2_REPO):
                use_compat_runner = False
        elif explicit_repo_root is not None:
            if explicit_repo_root == MEDSAM2_REPO or _path_is_within(explicit_repo_root, MEDSAM2_REPO):
                use_compat_runner = True
            elif explicit_repo_root == MEDICAL_SAM2_REPO or _path_is_within(explicit_repo_root, MEDICAL_SAM2_REPO):
                use_compat_runner = False
        elif _is_medsam2_release_checkpoint(requested_ckpt):
            use_compat_runner = True

        if explicit_runner_selector == COMPAT_RUNNER_ALIAS:
            runner_path = MEDSAM2_RUNNER
        elif explicit_runner_selector == LEGACY_RUNNER_ALIAS:
            runner_path = MEDICAL_SAM2_RUNNER
        elif explicit_runner_path is not None:
            runner_path = explicit_runner_path
        else:
            runner_path = MEDSAM2_RUNNER if use_compat_runner else MEDICAL_SAM2_RUNNER

        if not runner_path.exists():
            raise SegEntryError(
                f"MedSAM2 runner not found: {runner_path}",
                code="medsam2_runner_not_found",
                status=500,
            )

        repo_root = explicit_repo_root or (MEDSAM2_REPO if use_compat_runner else MEDICAL_SAM2_REPO)
        sam_ckpt = requested_ckpt or (COMPAT_DEFAULT_CKPT if use_compat_runner else LEGACY_DEFAULT_CKPT)
        sam_config = (
            _normalize_compat_config(request.engine.medsam2_config)
            if use_compat_runner
            else _normalize_legacy_config(request.engine.medsam2_config)
        )
        image_size = request.engine.medsam2_image_size or (
            COMPAT_DEFAULT_IMAGE_SIZE if use_compat_runner else LEGACY_DEFAULT_IMAGE_SIZE
        )

        if not sam_ckpt.exists():
            raise SegEntryError(
                f"MedSAM2 checkpoint not found: {sam_ckpt}",
                code="medsam2_ckpt_not_found",
                status=500,
            )

        engine_root = context.engine_dir / "medsam2"
        engine_root.mkdir(parents=True, exist_ok=True)
        context.plans_dir.mkdir(parents=True, exist_ok=True)
        context.logs_dir.mkdir(parents=True, exist_ok=True)

        case_id = sanitize_name(request.request_id or "medsam2_case")
        case_payload = {
            "case_id": case_id,
            "input_path": request.input_path,
            "input_type": "nifti_file" if request.input_type == "nifti_file" else "dicom_dir",
            "modality": request.modality,
            "modality_source": "seg-entry",
            "relative_input": Path(request.input_path).name,
            "prompts": [prompt.to_dict() for prompt in request.prompts],
            "metadata": request.metadata,
        }
        case_file = context.plans_dir / "medsam2_case.json"
        case_file.write_text(json.dumps(case_payload, indent=2, ensure_ascii=False), encoding="utf-8")

        log_file = context.logs_dir / "medsam2.log"
        cmd = [
            request.engine.python_bin or default_medsam2_python(),
            str(runner_path),
            "_worker",
            "--case-file",
            str(case_file),
            "--output-root",
            str(engine_root),
            "--sam-ckpt",
            str(sam_ckpt),
            "--sam-config",
            str(sam_config),
            "--image-size",
            str(int(image_size)),
            "--device",
            "gpu",
            "--export-mode",
            request.engine.export_mode,
        ]
        if request.engine.overwrite:
            cmd.append("--overwrite")
        if request.engine.quiet:
            cmd.append("--quiet")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        execution_metadata = {
            "device": request.engine.device,
            "gpu_selection": None,
        }

        gpu_selection = select_gpu(request.engine)
        assert gpu_selection is not None
        env["CUDA_VISIBLE_DEVICES"] = gpu_selection.visible_devices
        execution_metadata["gpu_selection"] = gpu_selection.to_dict()

        with log_file.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(
                cmd,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )

        if completed.returncode != 0:
            raise SegEntryError(
                "MedSAM2 workflow failed. Check the engine log for details.",
                code="medsam2_run_failed",
                status=500,
                details={
                    "returncode": completed.returncode,
                    "log_path": str(log_file),
                    "command": cmd,
                },
            )

        case_dir = engine_root / case_id
        exports_dir = case_dir / "exports"
        case_summary_path = case_dir / "case.json"
        primary_mask_path = exports_dir / "liver_tumor.nii.gz"

        if not exports_dir.exists():
            raise SegEntryError(
                f"Expected export directory is missing: {exports_dir}",
                code="medsam2_exports_missing",
                status=500,
            )
        if not case_summary_path.exists():
            raise SegEntryError(
                f"Expected case summary is missing: {case_summary_path}",
                code="medsam2_case_summary_missing",
                status=500,
            )
        if not primary_mask_path.exists():
            raise SegEntryError(
                f"Expected primary mask is missing: {primary_mask_path}",
                code="medsam2_primary_mask_missing",
                status=500,
            )

        case_summary = json.loads(case_summary_path.read_text(encoding="utf-8"))

        artifacts = [
            Artifact(
                name="liver_tumor",
                role="primary_mask",
                path=str(primary_mask_path),
                format="nii.gz",
                description="Prompt-driven MedSAM2 liver tumor mask",
            )
        ]

        diameter_path = exports_dir / "liver_tumor_diameter.json"
        if diameter_path.exists():
            artifacts.append(
                Artifact(
                    name="liver_tumor_diameter",
                    role="native_metadata",
                    path=str(diameter_path),
                    format="json",
                    description="Largest diameter measurement on predicted tumor mask",
                )
            )

        prompt_plan_path = exports_dir / "prompt_plan.json"
        if prompt_plan_path.exists():
            artifacts.append(
                Artifact(
                    name="prompt_plan",
                    role="native_metadata",
                    path=str(prompt_plan_path),
                    format="json",
                    description="Normalized prompts applied in MedSAM2 workflow",
                )
            )

        prompt_render_index_path = exports_dir / "prompt_render_index.json"
        if prompt_render_index_path.exists():
            artifacts.append(
                Artifact(
                    name="prompt_render_index",
                    role="native_metadata",
                    path=str(prompt_render_index_path),
                    format="json",
                    description="Rendered prompt PNG index and primary preview pointer",
                )
            )

        prompt_render_primary_path = exports_dir / "prompt_render_primary.png"
        if prompt_render_primary_path.exists():
            artifacts.append(
                Artifact(
                    name="prompt_render_primary",
                    role="native_preview",
                    path=str(prompt_render_primary_path),
                    format="png",
                    description="Prompt overlay preview on the source slice for coordinate sanity check",
                )
            )

        artifacts.append(
            Artifact(
                name="case_summary",
                role="native_metadata",
                path=str(case_summary_path),
                format="json",
                description="Native MedSAM2 case summary",
            )
        )
        artifacts.append(
            Artifact(
                name="engine_log",
                role="native_log",
                path=str(log_file),
                format="log",
                description="MedSAM2 worker log",
            )
        )

        return AdapterResult(
            artifacts=artifacts,
            primary_artifact=str(primary_mask_path),
            native_output_dir=str(case_dir),
            log_path=str(log_file),
            metadata={
                "engine": "medsam2",
                "engine_case_id": case_id,
                "engine_summary": case_summary,
                "prompt_policy": "required",
                "prompt_count": len(request.prompts),
                "runner_family": "medsam2_compat" if use_compat_runner else "medical_sam2_legacy",
                "runner_path": str(runner_path),
                "repo_root": str(repo_root),
                "sam": {
                    "checkpoint": str(sam_ckpt),
                    "config": case_summary.get("sam_config", sam_config),
                    "image_size": int(case_summary.get("image_size", image_size)),
                    "requested_image_size": int(image_size),
                },
                "execution": execution_metadata,
            },
        )
