from __future__ import annotations

from .adapters.base import SegmentationAdapter
from .adapters.medsam2 import MedSam2Adapter
from .adapters.totalsegmentator import TotalSegmentatorAdapter
from .errors import SegEntryError


def build_registry() -> dict[str, SegmentationAdapter]:
    return {
        "totalsegmentator": TotalSegmentatorAdapter(),
        "medsam2": MedSam2Adapter(),
    }


def get_adapter(model_name: str) -> SegmentationAdapter:
    registry = build_registry()
    if model_name not in registry:
        raise SegEntryError(
            f"Unsupported model: {model_name}",
            code="unsupported_model",
            status=400,
            details={"supported": sorted(registry)},
        )
    return registry[model_name]


def describe_models() -> list[dict]:
    return [adapter.capability.to_dict() for adapter in build_registry().values()]
