from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

SUPPORTED_MODELS = {"totalsegmentator", "medsam2"}
SUPPORTED_TARGETS = {"liver"}
SUPPORTED_INPUT_TYPES = {"auto", "nifti_file", "dicom_dir"}
SUPPORTED_MODALITIES = {"ct", "mr"}


class SegEntryModel(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
        validate_assignment=True,
    )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="python")


class PromptPoint(SegEntryModel):
    x: float = Field(..., description="Prompt X coordinate.")
    y: float = Field(..., description="Prompt Y coordinate.")
    label: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Prompt point label: 1 positive, 0 negative.",
    )


class SegmentationPrompt(SegEntryModel):
    kind: str = Field(..., min_length=1, description="Prompt type, for example bbox_2d.")
    frame_index: Optional[int] = Field(default=None, alias="frameIndex", ge=0)
    bbox: Optional[list[int]] = Field(default=None, min_length=4, max_length=4)
    points: list[PromptPoint] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("bbox")
    @classmethod
    def _validate_bbox(cls, value: Optional[list[int]]) -> Optional[list[int]]:
        if value is None:
            return value
        if any(item < 0 for item in value):
            raise ValueError("bbox values must be >= 0")
        if value[2] <= value[0] or value[3] <= value[1]:
            raise ValueError("bbox must satisfy x1 > x0 and y1 > y0")
        return value

    @field_validator("kind")
    @classmethod
    def _normalize_kind(cls, value: str) -> str:
        return value.strip().lower()


class EngineConfig(SegEntryModel):
    python_bin: Optional[str] = Field(default=None, alias="pythonBin")
    device: str = Field(default="gpu")
    gpu_policy: str = Field(default="auto_best", alias="gpuPolicy")
    gpu_candidates: Optional[str] = Field(default=None, alias="gpuCandidates")
    gpu_id: Optional[int] = Field(default=None, alias="gpuId", ge=0)
    gpu_min_free_memory_mb: int = Field(default=4096, alias="gpuMinFreeMemoryMb", ge=1)
    cuda_visible_devices: Optional[str] = Field(default=None, alias="cudaVisibleDevices")
    quiet: bool = Field(default=False)
    overwrite: bool = Field(default=False)
    export_mode: str = Field(default="copy", alias="exportMode")
    nr_thr_resamp: int = Field(default=1, alias="nrThrResamp", ge=1)
    nr_thr_saving: int = Field(default=1, alias="nrThrSaving", ge=1)
    totalseg_home: Optional[str] = Field(default=None, alias="totalsegHome")
    totalseg_runner: Optional[str] = Field(default=None, alias="totalsegRunner")
    totalseg_task_profile: str = Field(default="core_liver", alias="totalsegTaskProfile")
    medsam2_repo: Optional[str] = Field(default=None, alias="medsam2Repo")
    medsam2_runner: Optional[str] = Field(default=None, alias="medsam2Runner")
    medsam2_ckpt: Optional[str] = Field(default=None, alias="medsam2Ckpt")
    medsam2_config: Optional[str] = Field(default=None, alias="medsam2Config")
    medsam2_image_size: Optional[int] = Field(default=None, alias="medsam2ImageSize", ge=1)
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("device", "gpu_policy", "export_mode", "totalseg_task_profile")
    @classmethod
    def _normalize_engine_modes(cls, value: str) -> str:
        return value.strip().lower()


class SegmentationRequest(SegEntryModel):
    request_id: Optional[str] = Field(default=None, alias="requestId")
    input_path: str = Field(..., alias="inputPath")
    input_type: str = Field(default="auto", alias="inputType")
    target: str = Field(default="liver")
    model: str = Field(default="totalsegmentator")
    modality: Optional[str] = Field(default=None)
    output_dir: Optional[str] = Field(default=None, alias="outputDir")
    prompts: list[SegmentationPrompt] = Field(default_factory=list)
    engine: EngineConfig = Field(default_factory=EngineConfig)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("input_type", "target", "model", "modality")
    @classmethod
    def _normalize_request_keys(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return value.strip().lower()


class Artifact(SegEntryModel):
    name: str
    role: str
    path: str
    format: str
    description: str


class SegmentationResponse(SegEntryModel):
    request_id: str = Field(..., alias="requestId")
    status: str
    model: str
    target: str
    input_path: str = Field(..., alias="inputPath")
    input_type: str = Field(..., alias="inputType")
    modality: Optional[str]
    output_dir: str = Field(..., alias="outputDir")
    artifacts: list[Artifact] = Field(default_factory=list)
    primary_artifact: Optional[str] = Field(default=None, alias="primaryArtifact")
    native_output_dir: Optional[str] = Field(default=None, alias="nativeOutputDir")
    log_path: Optional[str] = Field(default=None, alias="logPath")
    timings: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: Optional[dict[str, Any]] = Field(default=None)
