from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from ..contracts import Artifact, SegmentationRequest
from ..errors import SegEntryError
from ..gpu import select_gpu
from ..inputs import sanitize_name
from ..paths import (
    MRSEGMENTATOR_REPO,
    MRSEGMENTATOR_WEIGHTS_ROOT,
    default_mrsegmentator_python,
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


SUPPORTED_TARGETS = {"liver", "mr_abdomen_organs"}


class MRSegmentatorAdapter(SegmentationAdapter):
    capability = ModelCapability(
        name="mrsegmentator",
        status="pilot",
        targets=("liver", "mr_abdomen_organs"),
        input_types=("nifti_file", "dicom_dir"),
        supported_modalities=("mr",),
        prompt_required=False,
        prompt_kinds=(),
        service_contract_version=MODEL_STANDARD_VERSION,
        segmentation_output_format=SEGMENTATION_OUTPUT_FORMAT,
        sidecar_formats=SIDECAR_FORMATS,
        notes=(
            "Runs the local MRSegmentator base model in its own uv environment. "
            "target='liver' returns a binary liver primary mask; "
            "target='mr_abdomen_organs' returns the native multi-label mask as primary "
            "for multi-segment DICOM SEG conversion by ai-orchestrator."
        ),
    )

    def validate_request(self, request: SegmentationRequest) -> None:
        if request.target not in SUPPORTED_TARGETS:
            raise SegEntryError(
                "MRSegmentator supports target='liver' or target='mr_abdomen_organs'.",
                code="unsupported_target",
                status=400,
                details={"supported": sorted(SUPPORTED_TARGETS)},
            )

        if request.input_type not in {"nifti_file", "dicom_dir"}:
            raise SegEntryError(
                "MRSegmentator input_type must be 'nifti_file' or 'dicom_dir'.",
                code="invalid_input_type",
                status=400,
            )

        if request.modality != "mr":
            raise SegEntryError(
                "MRSegmentator adapter currently requires modality='mr'.",
                code="invalid_modality",
                status=400,
                details={"supported": ["mr"]},
            )

        if request.prompts:
            raise SegEntryError(
                "MRSegmentator is automatic and does not accept prompts.",
                code="prompt_not_supported",
                status=400,
            )

        if request.engine.device not in {"gpu", "cpu"}:
            raise SegEntryError(
                "MRSegmentator device must be 'gpu' or 'cpu'.",
                code="invalid_device",
                status=400,
            )

        if request.engine.export_mode not in {"copy", "symlink"}:
            raise SegEntryError(
                "MRSegmentator export_mode must be 'copy' or 'symlink'.",
                code="invalid_export_mode",
                status=400,
            )

    def run(self, request: SegmentationRequest, context: RunContext) -> AdapterResult:
        self.validate_request(request)

        repo_root = Path(request.engine.mrsegmentator_repo or MRSEGMENTATOR_REPO).expanduser().resolve()
        runner_path = Path(
            request.engine.mrsegmentator_runner or repo_root / "scripts" / "run_liver_workflow.py"
        ).expanduser().resolve()
        weights_root = Path(
            request.engine.mrsegmentator_weights_root
            or (repo_root / "weights" if repo_root != MRSEGMENTATOR_REPO else MRSEGMENTATOR_WEIGHTS_ROOT)
        ).expanduser().resolve()
        python_bin = Path(request.engine.mrsegmentator_python_bin or default_mrsegmentator_python()).expanduser()

        if not runner_path.exists():
            raise SegEntryError(
                f"MRSegmentator runner not found: {runner_path}",
                code="mrsegmentator_runner_not_found",
                status=500,
            )
        if not python_bin.exists():
            raise SegEntryError(
                f"MRSegmentator Python executable not found: {python_bin}",
                code="mrsegmentator_python_not_found",
                status=500,
            )
        self._assert_weights_ready(weights_root)

        engine_root = context.engine_dir / "mrsegmentator"
        engine_root.mkdir(parents=True, exist_ok=True)
        context.plans_dir.mkdir(parents=True, exist_ok=True)
        context.logs_dir.mkdir(parents=True, exist_ok=True)

        case_id = sanitize_name(request.request_id or "mrsegmentator_case")
        case_payload = {
            "case_id": case_id,
            "input_path": request.input_path,
            "input_type": request.input_type,
            "modality": request.modality,
            "modality_source": "seg-entry",
            "relative_input": Path(request.input_path).name,
            "metadata": request.metadata,
        }
        case_file = context.plans_dir / "mrsegmentator_case.json"
        case_file.write_text(json.dumps(case_payload, indent=2, ensure_ascii=False), encoding="utf-8")

        log_file = context.logs_dir / "mrsegmentator.log"
        cmd = [
            str(python_bin),
            str(runner_path),
            "_worker",
            "--case-file",
            str(case_file),
            "--output-root",
            str(engine_root),
            "--weights-root",
            str(weights_root),
            "--device",
            request.engine.device,
            "--export-mode",
            request.engine.export_mode,
            "--split-level",
            str(request.engine.mrsegmentator_split_level),
            "--split-margin",
            str(request.engine.mrsegmentator_split_margin),
            "--batchsize",
            str(request.engine.mrsegmentator_batchsize),
            "--nproc",
            str(request.engine.mrsegmentator_nproc),
            "--nproc-export",
            str(request.engine.mrsegmentator_nproc_export),
        ]
        if request.engine.mrsegmentator_fast:
            cmd.append("--fast")
        else:
            cmd.append("--no-fast")
        if request.engine.mrsegmentator_fold is not None:
            cmd.extend(["--fold", str(request.engine.mrsegmentator_fold)])
        if request.engine.mrsegmentator_export_empty:
            cmd.append("--export-empty")
        if request.engine.overwrite:
            cmd.append("--overwrite")
        if request.engine.quiet:
            cmd.append("--quiet")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        execution_metadata: dict[str, Any] = {
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
                "MRSegmentator workflow failed. Check the engine log for details.",
                code="mrsegmentator_run_failed",
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
                f"Expected MRSegmentator export directory is missing: {exports_dir}",
                code="mrsegmentator_exports_missing",
                status=500,
            )
        if not case_summary_path.exists():
            raise SegEntryError(
                f"Expected MRSegmentator case summary is missing: {case_summary_path}",
                code="mrsegmentator_case_summary_missing",
                status=500,
            )

        case_summary = json.loads(case_summary_path.read_text(encoding="utf-8"))
        artifacts, primary_artifact = self._build_artifacts(request.target, exports_dir, case_summary)
        artifacts.append(
            Artifact(
                name="case_summary",
                role="native_metadata",
                path=str(case_summary_path),
                format="json",
                description="Native MRSegmentator case summary",
            )
        )
        artifacts.append(
            Artifact(
                name="engine_log",
                role="native_log",
                path=str(log_file),
                format="log",
                description="MRSegmentator worker log",
            )
        )

        return AdapterResult(
            artifacts=artifacts,
            primary_artifact=primary_artifact,
            native_output_dir=str(case_dir),
            log_path=str(log_file),
            metadata={
                "engine": "mrsegmentator",
                "engine_case_id": case_id,
                "engine_summary": case_summary,
                "repo_root": str(repo_root),
                "runner_path": str(runner_path),
                "weights_root": str(weights_root),
                "target_policy": (
                    "native_multilabel_primary"
                    if request.target == "mr_abdomen_organs"
                    else "liver_binary_primary"
                ),
                "execution": execution_metadata,
            },
        )

    def _assert_weights_ready(self, weights_root: Path) -> None:
        base_dir = weights_root / "base"
        checkpoint_count = len(list(base_dir.rglob("checkpoint_final.pth"))) if base_dir.exists() else 0
        if not (base_dir / "plans.json").is_file() or checkpoint_count == 0:
            raise SegEntryError(
                "MRSegmentator base weights are not ready.",
                code="mrsegmentator_weights_not_ready",
                status=500,
                details={
                    "weights_root": str(weights_root),
                    "base_dir": str(base_dir),
                    "plans_json_exists": (base_dir / "plans.json").is_file(),
                    "checkpoint_count": checkpoint_count,
                },
            )

    def _build_artifacts(
        self,
        target: str,
        exports_dir: Path,
        case_summary: dict[str, Any],
    ) -> tuple[list[Artifact], str]:
        exports = case_summary.get("exports") if isinstance(case_summary.get("exports"), dict) else {}
        native_multilabel = exports.get("native_multilabel") or str(
            exports_dir / "mrsegmentator_multilabel.nii.gz"
        )
        liver_path = exports_dir / "liver.nii.gz"
        native_multilabel_path = Path(str(native_multilabel))

        if not liver_path.exists():
            raise SegEntryError(
                f"Expected MRSegmentator liver export is missing: {liver_path}",
                code="mrsegmentator_liver_missing",
                status=500,
            )
        if not native_multilabel_path.exists():
            raise SegEntryError(
                f"Expected MRSegmentator multi-label export is missing: {native_multilabel_path}",
                code="mrsegmentator_multilabel_missing",
                status=500,
            )

        artifacts: list[Artifact] = []
        if target == "mr_abdomen_organs":
            artifacts.append(
                Artifact(
                    name="mr_abdomen_organs",
                    role="primary_mask",
                    path=str(native_multilabel_path),
                    format="nii.gz",
                    description="MRSegmentator native multi-label abdomen organ mask",
                )
            )
            primary_artifact = str(native_multilabel_path)
        else:
            artifacts.append(
                Artifact(
                    name="liver",
                    role="primary_mask",
                    path=str(liver_path),
                    format="nii.gz",
                    description="MRSegmentator binary liver mask",
                )
            )
            artifacts.append(
                Artifact(
                    name="mrsegmentator_multilabel",
                    role="supporting_mask",
                    path=str(native_multilabel_path),
                    format="nii.gz",
                    description="MRSegmentator native multi-label abdomen organ mask",
                )
            )
            primary_artifact = str(liver_path)

        label_exports = exports.get("label_exports") if isinstance(exports.get("label_exports"), list) else []
        for item in label_exports:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            path = str(item.get("path") or "").strip()
            if not name or not path:
                continue
            if target == "liver" and name == "liver":
                continue
            artifacts.append(
                Artifact(
                    name=name,
                    role="supporting_mask",
                    path=path,
                    format="nii.gz",
                    description=f"MRSegmentator binary mask for {name}",
                )
            )

        return artifacts, primary_artifact
