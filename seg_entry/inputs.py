from __future__ import annotations

import re
from pathlib import Path

from .contracts import SUPPORTED_INPUT_TYPES
from .errors import SegEntryError


def sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._-")
    return cleaned or "request"


def resolve_input_path(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise SegEntryError(
            f"Input path does not exist: {path}",
            code="input_not_found",
            status=400,
        )
    return path


def is_nifti_file(path: Path) -> bool:
    return path.is_file() and (path.name.endswith(".nii") or path.name.endswith(".nii.gz"))


def looks_like_dicom_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    files = [child for child in sorted(path.iterdir()) if child.is_file()]
    if not files:
        return False
    for child in files[:32]:
        suffix = child.suffix.lower()
        if suffix == ".dcm":
            return True
        if suffix in {".ima", ".dicom"}:
            return True
    return False


def detect_input_type(path: Path, hint: str = "auto") -> str:
    if hint not in SUPPORTED_INPUT_TYPES:
        raise SegEntryError(
            f"Unsupported input_type: {hint}",
            code="invalid_input_type",
            status=400,
            details={"supported": sorted(SUPPORTED_INPUT_TYPES)},
        )

    if hint == "nifti_file":
        if not is_nifti_file(path):
            raise SegEntryError(
                f"Expected a NIfTI file, got: {path}",
                code="invalid_nifti_input",
                status=400,
            )
        return hint

    if hint == "dicom_dir":
        if not looks_like_dicom_dir(path):
            raise SegEntryError(
                f"Expected a DICOM directory, got: {path}",
                code="invalid_dicom_input",
                status=400,
            )
        return hint

    if is_nifti_file(path):
        return "nifti_file"
    if looks_like_dicom_dir(path):
        return "dicom_dir"

    raise SegEntryError(
        "Could not infer input_type automatically. Please set input_type explicitly to 'nifti_file' or 'dicom_dir'.",
        code="cannot_infer_input_type",
        status=400,
        details={"input_path": str(path)},
    )
