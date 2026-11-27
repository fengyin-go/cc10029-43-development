"""教学成果送审材料包接口：证据包导出、包状态核验、凭包受理上报。

独立于通用资源路由：导出/受理不是简单的状态流转，需要包编号、材料快照等
领域数据，统一由 TeachAwardService 完成业务判断。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.schemas import ActionResult
from app.services import service_for
from app.services.teach_award import TeachAwardService

router = APIRouter(prefix="/api/teach_award", tags=["教学成果送审材料包"])


class SubmitPayload(BaseModel):
    package_no: str


class PackageResult(BaseModel):
    ok: bool
    message: str
    package: dict[str, Any] | None = None


def _service() -> TeachAwardService:
    service = service_for("teach_award")
    assert isinstance(service, TeachAwardService)
    return service


@router.post("/{entry_id}/package", response_model=PackageResult)
def export_package(entry_id: int) -> PackageResult:
    """从已初审成果导出证据包；同一成果重复导出返回同一个包。"""
    package, message = _service().export_package(entry_id)
    return PackageResult(ok=package is not None, message=message, package=package)


@router.get("/packages/{package_no}", response_model=PackageResult)
def verify_package(package_no: str) -> PackageResult:
    """按包编号核验：待受理（可受理）/已失效（需重新出包）/已受理（查当时材料）。"""
    view, message = _service().verify_package(package_no)
    return PackageResult(ok=view is not None, message=message, package=view)


@router.post("/{entry_id}/submit", response_model=ActionResult)
def submit_with_package(entry_id: int, payload: SubmitPayload) -> ActionResult:
    """评审员交回包编号后，凭包受理上报并在成果待办登记本次受理。"""
    entry, message = _service().submit_with_package(entry_id, payload.package_no.strip())
    return ActionResult(ok=entry is not None, message=message, entry=entry)
