from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable


SEG_ENTRY_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = SEG_ENTRY_ROOT.parent
DEFAULT_RUNS_ROOT = SEG_ENTRY_ROOT / "runs"
DEFAULT_GPU_CANDIDATES = "0,1,2,3,4,5,6,7"

TOTALSEG_REPO = WORKSPACE_ROOT / "TotalSegmentator"
TOTALSEG_RUNNER = TOTALSEG_REPO / "scripts" / "run_liver_workflow.py"
TOTALSEG_HOME = TOTALSEG_REPO / ".totalsegmentator"

MEDSAM2_REPO_CANDIDATES = [
    WORKSPACE_ROOT / "Medical-SAM2",
    WORKSPACE_ROOT / "MedSAM2",
]
MEDSAM2_REPO = next((path for path in MEDSAM2_REPO_CANDIDATES if path.exists()), MEDSAM2_REPO_CANDIDATES[0])
MEDSAM2_RUNNER = MEDSAM2_REPO / "scripts" / "run_liver_prompt_workflow.py"

KNOWN_ENGINE_PYTHONS = [
    Path("/home/gpu/miniconda3/envs/nnunet_py311/bin/python"),
    Path("/home/gpu/miniconda3/envs/medsam2/bin/python"),
    Path(sys.executable),
]

MEDSAM2_ENGINE_PYTHONS = [
    Path("/home/gpu/miniconda3/envs/medsam2/bin/python"),
    Path("/home/gpu/miniconda3/envs/nnunet_py311/bin/python"),
    Path(sys.executable),
]


def _first_existing(candidates: Iterable[Path]) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path(sys.executable)


def default_engine_python() -> str:
    return str(_first_existing(KNOWN_ENGINE_PYTHONS))


def default_medsam2_python() -> str:
    return str(_first_existing(MEDSAM2_ENGINE_PYTHONS))
