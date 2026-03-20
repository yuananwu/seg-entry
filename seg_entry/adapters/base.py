from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..contracts import Artifact, SegmentationRequest

MODEL_STANDARD_VERSION = "seg-entry-model-standard-v1"
SEGMENTATION_OUTPUT_FORMAT = "nii.gz"
SEGMENTATION_ARTIFACT_ROLES = {"primary_mask", "supporting_mask"}
SIDECAR_FORMATS = ("json", "log")


@dataclass(frozen=True)
class ModelCapability:
    name: str
    status: str
    targets: tuple[str, ...]
    input_types: tuple[str, ...]
    supported_modalities: tuple[str, ...]
    prompt_required: bool
    prompt_kinds: tuple[str, ...]
    service_contract_version: str
    segmentation_output_format: str
    sidecar_formats: tuple[str, ...]
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "targets": list(self.targets),
            "input_types": list(self.input_types),
            "supported_modalities": list(self.supported_modalities),
            "prompt_required": self.prompt_required,
            "prompt_kinds": list(self.prompt_kinds),
            "service_contract_version": self.service_contract_version,
            "segmentation_output_format": self.segmentation_output_format,
            "sidecar_formats": list(self.sidecar_formats),
            "notes": self.notes,
        }


@dataclass
class RunContext:
    request_dir: Path
    engine_dir: Path
    plans_dir: Path
    logs_dir: Path
    request_json_path: Path
    response_json_path: Path


@dataclass
class AdapterResult:
    artifacts: list[Artifact]
    primary_artifact: str | None
    native_output_dir: str | None
    log_path: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


class SegmentationAdapter(ABC):
    capability: ModelCapability

    @abstractmethod
    def validate_request(self, request: SegmentationRequest) -> None:
        raise NotImplementedError

    @abstractmethod
    def run(self, request: SegmentationRequest, context: RunContext) -> AdapterResult:
        raise NotImplementedError
