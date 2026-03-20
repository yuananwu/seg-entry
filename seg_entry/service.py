from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters.base import RunContext, SEGMENTATION_ARTIFACT_ROLES, SEGMENTATION_OUTPUT_FORMAT
from .contracts import (
    EngineConfig,
    SUPPORTED_MODELS,
    SUPPORTED_TARGETS,
    SegmentationRequest,
    SegmentationResponse,
)
from .errors import SegEntryError
from .inputs import detect_input_type, resolve_input_path, sanitize_name
from .paths import DEFAULT_RUNS_ROOT
from .registry import describe_models, get_adapter


@dataclass
class ServiceRunResult:
    response: SegmentationResponse
    status_code: int


class SegmentationService:
    def describe_models(self) -> list[dict[str, Any]]:
        return describe_models()

    def execute(self, payload: dict[str, Any]) -> ServiceRunResult:
        started_at = time.time()
        bootstrap_request = self._bootstrap_request(payload)
        active_request = bootstrap_request
        context = self._safe_build_context(bootstrap_request)
        self._write_json(context.request_json_path, payload)

        try:
            request = self._normalize_request(payload)
            active_request = request
            if request.output_dir != bootstrap_request.output_dir:
                context = self._build_context(request)
            self._write_json(context.request_json_path, request.to_dict())
            adapter = get_adapter(request.model)
            adapter.validate_request(request)
            adapter_result = adapter.run(request, context)
            self._assert_standard_segmentation_outputs(adapter_result.artifacts)
            response = SegmentationResponse(
                request_id=request.request_id or "",
                status="succeeded",
                model=request.model,
                target=request.target,
                input_path=request.input_path,
                input_type=request.input_type,
                modality=request.modality,
                output_dir=request.output_dir or "",
                artifacts=adapter_result.artifacts,
                primary_artifact=adapter_result.primary_artifact,
                native_output_dir=adapter_result.native_output_dir,
                log_path=adapter_result.log_path,
                timings={
                    "started_at_epoch": started_at,
                    "finished_at_epoch": time.time(),
                    "duration_sec": round(time.time() - started_at, 3),
                },
                metadata=adapter_result.metadata,
                error=None,
            )
            status_code = 200
        except SegEntryError as exc:
            response = self._build_error_response(active_request, context, started_at, exc)
            status_code = exc.status
        except Exception as exc:  # pragma: no cover
            response = self._build_error_response(
                active_request,
                context,
                started_at,
                SegEntryError(
                    "Unexpected internal error.",
                    code="internal_error",
                    status=500,
                    details={"type": type(exc).__name__, "message": str(exc)},
                ),
            )
            status_code = 500

        self._write_json(context.response_json_path, response.to_dict())
        return ServiceRunResult(response=response, status_code=status_code)

    def _normalize_request(self, payload: dict[str, Any]) -> SegmentationRequest:
        try:
            request = SegmentationRequest.from_dict(payload)
        except KeyError as exc:
            raise SegEntryError(
                "Missing required request field.",
                code="missing_field",
                status=400,
                details={"field": str(exc)},
            ) from exc
        request.request_id = request.request_id or self._generate_request_id()
        request.request_id = sanitize_name(request.request_id)
        request.target = request.target.lower()
        request.model = request.model.lower()
        if request.modality is not None:
            request.modality = request.modality.lower()

        if request.model not in SUPPORTED_MODELS:
            raise SegEntryError(
                f"Unsupported model: {request.model}",
                code="unsupported_model",
                status=400,
                details={"supported": sorted(SUPPORTED_MODELS)},
            )

        if request.target not in SUPPORTED_TARGETS:
            raise SegEntryError(
                f"Unsupported target: {request.target}",
                code="unsupported_target",
                status=400,
                details={"supported": sorted(SUPPORTED_TARGETS)},
            )

        input_path = resolve_input_path(request.input_path)
        request.input_path = str(input_path)
        request.input_type = detect_input_type(input_path, request.input_type)

        request.output_dir = self._resolve_output_dir(request.request_id, request.output_dir)

        return request

    def _bootstrap_request(self, payload: dict[str, Any]) -> SegmentationRequest:
        request_id = sanitize_name(str(payload.get("request_id") or self._generate_request_id()))
        output_dir = self._resolve_output_dir(request_id, payload.get("output_dir"))
        modality = payload.get("modality")
        if isinstance(modality, str):
            modality = modality.lower()
        return SegmentationRequest(
            request_id=request_id,
            input_path=str(payload.get("input_path", "")),
            input_type=str(payload.get("input_type", "auto")),
            target=str(payload.get("target", "liver")).lower(),
            model=str(payload.get("model", "totalsegmentator")).lower(),
            modality=modality,
            output_dir=output_dir,
            prompts=[],
            engine=EngineConfig.from_dict(payload.get("engine")),
            metadata=dict(payload.get("metadata", {})),
        )

    def _build_context(self, request: SegmentationRequest) -> RunContext:
        request_dir = Path(request.output_dir or "").expanduser().resolve()
        try:
            request_dir.mkdir(parents=True, exist_ok=True)
            engine_dir = request_dir / "engine"
            plans_dir = request_dir / "plans"
            logs_dir = request_dir / "logs"
            engine_dir.mkdir(parents=True, exist_ok=True)
            plans_dir.mkdir(parents=True, exist_ok=True)
            logs_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SegEntryError(
                "Output directory is not writable or cannot be created.",
                code="invalid_output_dir",
                status=400,
                details={"output_dir": str(request_dir), "message": str(exc)},
            ) from exc
        return RunContext(
            request_dir=request_dir,
            engine_dir=engine_dir,
            plans_dir=plans_dir,
            logs_dir=logs_dir,
            request_json_path=request_dir / "request.json",
            response_json_path=request_dir / "response.json",
        )

    def _safe_build_context(self, request: SegmentationRequest) -> RunContext:
        try:
            return self._build_context(request)
        except SegEntryError:
            request.output_dir = str((DEFAULT_RUNS_ROOT / request.request_id).resolve())
            return self._build_context(request)

    def _build_error_response(
        self,
        request: SegmentationRequest,
        context: RunContext,
        started_at: float,
        error: SegEntryError,
    ) -> SegmentationResponse:
        return SegmentationResponse(
            request_id=request.request_id or "",
            status="failed",
            model=request.model,
            target=request.target,
            input_path=request.input_path,
            input_type=request.input_type,
            modality=request.modality,
            output_dir=request.output_dir or str(context.request_dir),
            artifacts=[],
            primary_artifact=None,
            native_output_dir=None,
            log_path=None,
            timings={
                "started_at_epoch": started_at,
                "finished_at_epoch": time.time(),
                "duration_sec": round(time.time() - started_at, 3),
            },
            metadata={},
            error=error.to_dict(),
        )

    def _generate_request_id(self) -> str:
        return "{stamp}-{suffix}".format(
            stamp=time.strftime("%Y%m%d-%H%M%S"),
            suffix=uuid.uuid4().hex[:8],
        )

    def _resolve_output_dir(self, request_id: str, output_dir: str | None) -> str:
        if output_dir is None:
            return str((DEFAULT_RUNS_ROOT / request_id).resolve())
        return str(Path(output_dir).expanduser().resolve())

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _assert_standard_segmentation_outputs(self, artifacts: list) -> None:
        for artifact in artifacts:
            if artifact.role not in SEGMENTATION_ARTIFACT_ROLES:
                continue
            if artifact.format != SEGMENTATION_OUTPUT_FORMAT:
                raise SegEntryError(
                    "Adapters must return segmentation artifacts as nii.gz.",
                    code="invalid_segmentation_output_format",
                    status=500,
                    details={
                        "artifact": artifact.name,
                        "role": artifact.role,
                        "format": artifact.format,
                    },
                )
