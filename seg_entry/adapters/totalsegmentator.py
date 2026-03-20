from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from ..contracts import Artifact, SUPPORTED_MODALITIES, SegmentationRequest
from ..errors import SegEntryError
from ..gpu import select_gpu
from ..inputs import sanitize_name
from ..paths import TOTALSEG_HOME, TOTALSEG_RUNNER, default_engine_python
from .base import (
    AdapterResult,
    MODEL_STANDARD_VERSION,
    ModelCapability,
    RunContext,
    SEGMENTATION_OUTPUT_FORMAT,
    SIDECAR_FORMATS,
    SegmentationAdapter,
)


CT_EXPORTS = [
    ("liver.nii.gz", "primary_mask", "Primary liver mask"),
    ("liver_vessels.nii.gz", "supporting_mask", "Hepatic vessels mask"),
    ("liver_tumor.nii.gz", "supporting_mask", "Liver tumor mask from the liver_vessels task"),
]
for index in range(1, 9):
    CT_EXPORTS.append(
        (
            "liver_segment_{index}.nii.gz".format(index=index),
            "supporting_mask",
            "Couinaud liver segment {index}".format(index=index),
        )
    )

MR_EXPORTS = [
    ("liver.nii.gz", "primary_mask", "Primary liver mask"),
]
for index in range(1, 9):
    MR_EXPORTS.append(
        (
            "liver_segment_{index}.nii.gz".format(index=index),
            "supporting_mask",
            "MR Couinaud liver segment {index}".format(index=index),
        )
    )


class TotalSegmentatorAdapter(SegmentationAdapter):
    capability = ModelCapability(
        name="totalsegmentator",
        status="production",
        targets=("liver",),
        input_types=("nifti_file", "dicom_dir"),
        supported_modalities=("ct", "mr"),
        prompt_required=False,
        prompt_kinds=(),
        service_contract_version=MODEL_STANDARD_VERSION,
        segmentation_output_format=SEGMENTATION_OUTPUT_FORMAT,
        sidecar_formats=SIDECAR_FORMATS,
        notes="Uses the local liver workflow and returns standardized liver exports for CT or MR.",
    )

    def validate_request(self, request: SegmentationRequest) -> None:
        if request.target != "liver":
            raise SegEntryError(
                "TotalSegmentator adapter currently supports target='liver' only.",
                code="unsupported_target",
                status=400,
            )

        if request.modality not in SUPPORTED_MODALITIES:
            raise SegEntryError(
                "TotalSegmentator liver workflow requires modality='ct' or 'mr'.",
                code="modality_required",
                status=400,
                details={"supported": sorted(SUPPORTED_MODALITIES)},
            )

        if request.engine.device not in {"gpu", "cpu"}:
            raise SegEntryError(
                "TotalSegmentator device must be 'gpu' or 'cpu'.",
                code="invalid_device",
                status=400,
            )

        if request.engine.export_mode not in {"copy", "symlink"}:
            raise SegEntryError(
                "TotalSegmentator export_mode must be 'copy' or 'symlink'.",
                code="invalid_export_mode",
                status=400,
            )

        if request.engine.totalseg_task_profile not in {"core_liver", "full_liver"}:
            raise SegEntryError(
                "TotalSegmentator totalseg_task_profile must be 'core_liver' or 'full_liver'.",
                code="invalid_totalseg_task_profile",
                status=400,
            )

    def run(self, request: SegmentationRequest, context: RunContext) -> AdapterResult:
        self.validate_request(request)

        runner_path = Path(request.engine.totalseg_runner or TOTALSEG_RUNNER).expanduser().resolve()
        if not runner_path.exists():
            raise SegEntryError(
                f"TotalSegmentator runner not found: {runner_path}",
                code="totalseg_runner_not_found",
                status=500,
            )

        engine_root = context.engine_dir / "totalsegmentator"
        engine_root.mkdir(parents=True, exist_ok=True)
        context.plans_dir.mkdir(parents=True, exist_ok=True)
        context.logs_dir.mkdir(parents=True, exist_ok=True)

        case_id = sanitize_name(request.request_id or "totalseg_case")
        case_payload = {
            "case_id": case_id,
            "input_path": request.input_path,
            "input_type": "nifti" if request.input_type == "nifti_file" else "dicom",
            "modality": request.modality,
            "modality_source": "seg-entry",
            "relative_input": Path(request.input_path).name,
            "metadata": request.metadata,
        }
        case_file = context.plans_dir / "totalseg_case.json"
        case_file.write_text(json.dumps(case_payload, indent=2, ensure_ascii=False), encoding="utf-8")

        log_file = context.logs_dir / "totalsegmentator.log"
        cmd = [
            request.engine.python_bin or default_engine_python(),
            str(runner_path),
            "_worker",
            "--case-file",
            str(case_file),
            "--output-root",
            str(engine_root),
            "--totalseg-home",
            str(Path(request.engine.totalseg_home or TOTALSEG_HOME).expanduser().resolve()),
            "--device",
            request.engine.device,
            "--export-mode",
            request.engine.export_mode,
            "--nr-thr-resamp",
            str(request.engine.nr_thr_resamp),
            "--nr-thr-saving",
            str(request.engine.nr_thr_saving),
            "--task-profile",
            request.engine.totalseg_task_profile,
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
        if request.engine.device == "gpu":
            gpu_selection = select_gpu(request.engine)
            assert gpu_selection is not None
            env["CUDA_VISIBLE_DEVICES"] = gpu_selection.visible_devices
            execution_metadata["gpu_selection"] = gpu_selection.to_dict()
        elif request.engine.cuda_visible_devices:
            env["CUDA_VISIBLE_DEVICES"] = str(request.engine.cuda_visible_devices)

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
                "TotalSegmentator workflow failed. Check the engine log for details.",
                code="totalseg_run_failed",
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
        if not exports_dir.exists():
            raise SegEntryError(
                f"Expected export directory is missing: {exports_dir}",
                code="totalseg_exports_missing",
                status=500,
            )

        if not case_summary_path.exists():
            raise SegEntryError(
                f"Expected case summary is missing: {case_summary_path}",
                code="totalseg_case_summary_missing",
                status=500,
            )

        case_summary = json.loads(case_summary_path.read_text(encoding="utf-8"))
        artifacts = self._build_artifacts(request.modality, request.engine.totalseg_task_profile, exports_dir)
        artifacts.append(
            Artifact(
                name="case_summary",
                role="native_metadata",
                path=str(case_summary_path),
                format="json",
                description="Native TotalSegmentator case summary",
            )
        )
        artifacts.append(
            Artifact(
                name="engine_log",
                role="native_log",
                path=str(log_file),
                format="log",
                description="TotalSegmentator worker log",
            )
        )

        return AdapterResult(
            artifacts=artifacts,
            primary_artifact=str(exports_dir / "liver.nii.gz"),
            native_output_dir=str(case_dir),
            log_path=str(log_file),
            metadata={
                "engine": "totalsegmentator",
                "engine_case_id": case_id,
                "engine_summary": case_summary,
                "task_profile": request.engine.totalseg_task_profile,
                "prompt_policy": "ignored" if request.prompts else "not_applicable",
                "execution": execution_metadata,
            },
        )

    def _build_artifacts(self, modality: str | None, task_profile: str, exports_dir: Path) -> list[Artifact]:
        if task_profile == "core_liver":
            export_defs = [("liver.nii.gz", "primary_mask", "Primary liver mask")]
        else:
            export_defs = CT_EXPORTS if modality == "ct" else MR_EXPORTS
        artifacts = []
        for filename, role, description in export_defs:
            path = exports_dir / filename
            if not path.exists():
                raise SegEntryError(
                    f"Expected exported file is missing: {path}",
                    code="totalseg_export_missing",
                    status=500,
                )
            artifacts.append(
                Artifact(
                    name=filename.replace(".nii.gz", ""),
                    role=role,
                    path=str(path),
                    format="nii.gz",
                    description=description,
                )
            )
        return artifacts
