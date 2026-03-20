from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SUPPORTED_MODELS = {"totalsegmentator", "medsam2"}
SUPPORTED_TARGETS = {"liver"}
SUPPORTED_INPUT_TYPES = {"auto", "nifti_file", "dicom_dir"}
SUPPORTED_MODALITIES = {"ct", "mr"}


@dataclass
class PromptPoint:
    x: float
    y: float
    label: int = 1

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PromptPoint":
        return cls(
            x=float(payload["x"]),
            y=float(payload["y"]),
            label=int(payload.get("label", 1)),
        )


@dataclass
class SegmentationPrompt:
    kind: str
    frame_index: int | None = None
    bbox: list[int] | None = None
    points: list[PromptPoint] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SegmentationPrompt":
        points = [PromptPoint.from_dict(item) for item in payload.get("points", [])]
        bbox = payload.get("bbox")
        if bbox is not None:
            bbox = [int(value) for value in bbox]
        frame_index = payload.get("frame_index")
        return cls(
            kind=str(payload["kind"]),
            frame_index=None if frame_index is None else int(frame_index),
            bbox=bbox,
            points=points,
            metadata=dict(payload.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "frame_index": self.frame_index,
            "bbox": self.bbox,
            "points": [asdict(item) for item in self.points],
            "metadata": self.metadata,
        }


@dataclass
class EngineConfig:
    python_bin: str | None = None
    device: str = "gpu"
    gpu_policy: str = "auto_best"
    gpu_candidates: str | None = None
    gpu_id: int | None = None
    gpu_min_free_memory_mb: int = 4096
    cuda_visible_devices: str | None = None
    quiet: bool = False
    overwrite: bool = False
    export_mode: str = "copy"
    nr_thr_resamp: int = 1
    nr_thr_saving: int = 1
    totalseg_home: str | None = None
    totalseg_runner: str | None = None
    totalseg_task_profile: str = "core_liver"
    medsam2_repo: str | None = None
    medsam2_runner: str | None = None
    medsam2_ckpt: str | None = None
    medsam2_config: str | None = None
    medsam2_image_size: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "EngineConfig":
        payload = payload or {}
        medsam2_image_size = payload.get("medsam2_image_size")
        return cls(
            python_bin=payload.get("python_bin"),
            device=str(payload.get("device", "gpu")),
            gpu_policy=str(payload.get("gpu_policy", "auto_best")).lower(),
            gpu_candidates=payload.get("gpu_candidates"),
            gpu_id=None if payload.get("gpu_id") is None else int(payload.get("gpu_id")),
            gpu_min_free_memory_mb=int(payload.get("gpu_min_free_memory_mb", 4096)),
            cuda_visible_devices=payload.get("cuda_visible_devices"),
            quiet=bool(payload.get("quiet", False)),
            overwrite=bool(payload.get("overwrite", False)),
            export_mode=str(payload.get("export_mode", "copy")),
            nr_thr_resamp=int(payload.get("nr_thr_resamp", 1)),
            nr_thr_saving=int(payload.get("nr_thr_saving", 1)),
            totalseg_home=payload.get("totalseg_home"),
            totalseg_runner=payload.get("totalseg_runner"),
            totalseg_task_profile=str(payload.get("totalseg_task_profile", "core_liver")).lower(),
            medsam2_repo=payload.get("medsam2_repo"),
            medsam2_runner=payload.get("medsam2_runner"),
            medsam2_ckpt=payload.get("medsam2_ckpt"),
            medsam2_config=payload.get("medsam2_config"),
            medsam2_image_size=None if medsam2_image_size is None else int(medsam2_image_size),
            extra=dict(payload.get("extra", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SegmentationRequest:
    request_id: str | None
    input_path: str
    input_type: str = "auto"
    target: str = "liver"
    model: str = "totalsegmentator"
    modality: str | None = None
    output_dir: str | None = None
    prompts: list[SegmentationPrompt] = field(default_factory=list)
    engine: EngineConfig = field(default_factory=EngineConfig)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SegmentationRequest":
        prompts = [SegmentationPrompt.from_dict(item) for item in payload.get("prompts", [])]
        return cls(
            request_id=payload.get("request_id"),
            input_path=str(payload["input_path"]),
            input_type=str(payload.get("input_type", "auto")),
            target=str(payload.get("target", "liver")),
            model=str(payload.get("model", "totalsegmentator")),
            modality=payload.get("modality"),
            output_dir=payload.get("output_dir"),
            prompts=prompts,
            engine=EngineConfig.from_dict(payload.get("engine")),
            metadata=dict(payload.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "input_path": self.input_path,
            "input_type": self.input_type,
            "target": self.target,
            "model": self.model,
            "modality": self.modality,
            "output_dir": self.output_dir,
            "prompts": [item.to_dict() for item in self.prompts],
            "engine": self.engine.to_dict(),
            "metadata": self.metadata,
        }


@dataclass
class Artifact:
    name: str
    role: str
    path: str
    format: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SegmentationResponse:
    request_id: str
    status: str
    model: str
    target: str
    input_path: str
    input_type: str
    modality: str | None
    output_dir: str
    artifacts: list[Artifact] = field(default_factory=list)
    primary_artifact: str | None = None
    native_output_dir: str | None = None
    log_path: str | None = None
    timings: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "status": self.status,
            "model": self.model,
            "target": self.target,
            "input_path": self.input_path,
            "input_type": self.input_type,
            "modality": self.modality,
            "output_dir": self.output_dir,
            "artifacts": [item.to_dict() for item in self.artifacts],
            "primary_artifact": self.primary_artifact,
            "native_output_dir": self.native_output_dir,
            "log_path": self.log_path,
            "timings": self.timings,
            "metadata": self.metadata,
            "error": self.error,
        }
