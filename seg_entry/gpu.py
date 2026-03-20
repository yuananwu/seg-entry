from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Iterable

from .contracts import EngineConfig
from .errors import SegEntryError
from .paths import DEFAULT_GPU_CANDIDATES


GPU_POLICY_AUTO_BEST = "auto_best"
GPU_POLICY_MANUAL = "manual"
SUPPORTED_GPU_POLICIES = {GPU_POLICY_AUTO_BEST, GPU_POLICY_MANUAL}


@dataclass(frozen=True)
class GPUStatus:
    index: int
    name: str
    memory_total_mb: int
    memory_used_mb: int
    memory_free_mb: int
    utilization_gpu_pct: int

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "name": self.name,
            "memory_total_mb": self.memory_total_mb,
            "memory_used_mb": self.memory_used_mb,
            "memory_free_mb": self.memory_free_mb,
            "utilization_gpu_pct": self.utilization_gpu_pct,
        }


@dataclass(frozen=True)
class GPUSelection:
    policy: str
    selected_gpu: GPUStatus
    candidates: tuple[GPUStatus, ...]
    visible_devices: str

    def to_dict(self) -> dict:
        return {
            "policy": self.policy,
            "selected_gpu": self.selected_gpu.to_dict(),
            "candidates": [item.to_dict() for item in self.candidates],
            "visible_devices": self.visible_devices,
        }


def parse_gpu_candidates(value: str | None, default: str | None = None) -> list[int]:
    text = value if value is not None else default
    if text is None:
        return []
    text = str(text).strip()
    if not text:
        return []

    gpu_ids: list[int] = []
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        gpu_ids.append(int(item))
    return gpu_ids


def query_gpu_status(candidate_ids: Iterable[int] | None = None) -> list[GPUStatus]:
    if shutil.which("nvidia-smi") is None:
        raise SegEntryError(
            "GPU probe is unavailable because 'nvidia-smi' was not found.",
            code="gpu_probe_unavailable",
            status=500,
        )

    cmd = [
        "nvidia-smi",
        "--query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if completed.returncode != 0:
        raise SegEntryError(
            "GPU probe failed before inference startup.",
            code="gpu_probe_failed",
            status=500,
            details={
                "returncode": completed.returncode,
                "stderr": completed.stderr.strip(),
            },
        )

    requested = None if candidate_ids is None else {int(item) for item in candidate_ids}
    statuses: list[GPUStatus] = []
    for line in completed.stdout.splitlines():
        parts = [item.strip() for item in line.split(",")]
        if len(parts) != 6:
            continue
        status = GPUStatus(
            index=int(parts[0]),
            name=parts[1],
            memory_total_mb=int(parts[2]),
            memory_used_mb=int(parts[3]),
            memory_free_mb=int(parts[4]),
            utilization_gpu_pct=int(parts[5]),
        )
        if requested is None or status.index in requested:
            statuses.append(status)

    if not statuses:
        raise SegEntryError(
            "No GPUs matched the candidate filter.",
            code="gpu_candidates_empty",
            status=400,
            details={"candidates": sorted(requested) if requested is not None else []},
        )
    return sorted(statuses, key=lambda item: item.index)


def select_gpu(engine: EngineConfig) -> GPUSelection | None:
    if engine.device == "cpu":
        return None

    if engine.gpu_policy not in SUPPORTED_GPU_POLICIES:
        raise SegEntryError(
            "Unsupported gpu_policy.",
            code="invalid_gpu_policy",
            status=400,
            details={"supported": sorted(SUPPORTED_GPU_POLICIES)},
        )

    if engine.gpu_policy == GPU_POLICY_MANUAL:
        if engine.gpu_id is None:
            raise SegEntryError(
                "gpu_id is required when gpu_policy='manual'.",
                code="gpu_id_required",
                status=400,
            )
        candidates = query_gpu_status([engine.gpu_id])
        selected = candidates[0]
        return GPUSelection(
            policy=engine.gpu_policy,
            selected_gpu=selected,
            candidates=tuple(candidates),
            visible_devices=str(selected.index),
        )

    candidate_text = engine.gpu_candidates
    if candidate_text is None and engine.cuda_visible_devices:
        candidate_text = engine.cuda_visible_devices
    candidate_ids = parse_gpu_candidates(candidate_text, default=DEFAULT_GPU_CANDIDATES)
    candidates = query_gpu_status(candidate_ids)
    eligible = [
        item for item in candidates
        if item.memory_free_mb >= int(engine.gpu_min_free_memory_mb)
    ]
    if not eligible:
        raise SegEntryError(
            "No candidate GPU satisfies the minimum free-memory requirement.",
            code="gpu_capacity_insufficient",
            status=503,
            details={
                "gpu_min_free_memory_mb": int(engine.gpu_min_free_memory_mb),
                "candidates": [item.to_dict() for item in candidates],
            },
        )

    selected = sorted(
        eligible,
        key=lambda item: (-item.memory_free_mb, item.utilization_gpu_pct, item.memory_used_mb, item.index),
    )[0]
    return GPUSelection(
        policy=engine.gpu_policy,
        selected_gpu=selected,
        candidates=tuple(candidates),
        visible_devices=str(selected.index),
    )


def build_gpu_status_payload(
    gpu_candidates: str | None = DEFAULT_GPU_CANDIDATES,
    gpu_min_free_memory_mb: int = 4096,
) -> dict:
    engine = EngineConfig(
        device="gpu",
        gpu_policy=GPU_POLICY_AUTO_BEST,
        gpu_candidates=gpu_candidates,
        gpu_min_free_memory_mb=gpu_min_free_memory_mb,
    )
    selection = select_gpu(engine)
    assert selection is not None
    return {
        "device": "gpu",
        "gpu_policy": engine.gpu_policy,
        "gpu_min_free_memory_mb": gpu_min_free_memory_mb,
        "selection": selection.to_dict(),
    }
