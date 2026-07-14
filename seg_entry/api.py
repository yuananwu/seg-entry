from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .contracts import SegmentationRequest, SegmentationResponse
from .errors import SegEntryError, resolve_http_status
from .gpu import build_gpu_status_payload
from .service import SegmentationService, ServiceRunResult

app = FastAPI(title="seg-entry", version="1.0.0")
service = SegmentationService()


@app.exception_handler(SegEntryError)
async def handle_seg_entry_error(_: Request, exc: SegEntryError) -> JSONResponse:
    status_code = resolve_http_status(exc)
    return JSONResponse(
        status_code=status_code,
        content={"status": "failed", "error": exc.to_dict()},
    )


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    error = SegEntryError(
        "Request validation failed.",
        code="invalid_request",
        status=400,
        details={"errors": exc.errors()},
    )
    return JSONResponse(
        status_code=400,
        content={"status": "failed", "error": error.to_dict()},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/models")
def models() -> dict[str, list[dict[str, Any]]]:
    return {"models": service.describe_models()}


@app.get("/runtime/gpus")
def runtime_gpus() -> dict[str, Any]:
    return build_gpu_status_payload()


@app.post(
    "/segmentations",
    response_model=SegmentationResponse,
    response_model_by_alias=False,
)
def create_segmentation(request: SegmentationRequest) -> SegmentationResponse:
    result = service.execute(request)
    if result.status_code >= 400:
        raise _error_from_service_result(result)
    return result.response


def _error_from_service_result(result: ServiceRunResult) -> SegEntryError:
    payload = result.response.error or {}
    details = payload.get("details", {})
    if not isinstance(details, dict):
        details = {"raw": details}
    return SegEntryError(
        message=str(payload.get("message", "Segmentation request failed.")),
        code=str(payload.get("code", "segmentation_failed")),
        status=result.status_code,
        details=details,
    )


def run_server(host: str = "0.0.0.0", port: int = 8010) -> None:
    try:
        import uvicorn
    except ModuleNotFoundError as exc:
        raise SegEntryError(
            "FastAPI server runtime dependency is missing.",
            code="dependency_missing",
            status=500,
            details={"package": "uvicorn"},
        ) from exc
    uvicorn.run(app, host=host, port=port)
