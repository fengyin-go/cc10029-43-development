"""教学成果申报领域服务：申报登记、初审、上报，含送审材料包导出、核验与受理。

送审材料包（证据包）把已初审成果的归档教案和观摩证明打包交给评审员：

- 仅"初审通过"的成果可导出材料包；同一成果重复导出返回同一个包，供传阅，
  全流程最终只登记一件送审成果。
- 评审员交回包编号后凭包受理上报，成果待办登记本次受理（包编号、受理时间）。
- 包内材料被注销（如资料员注销观摩证明）时包即失效：受理被拦截，
  需补齐证明重新出包，不允许把原教案和未确认的替代证明拼配受理。
- 已受理的包按原编号永久保留当时两件材料的快照，供日后核验。
- 材料包绑定成果，其他成果即使使用同名教案也不能凭该包上报。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store

# 送审材料包登记表：存在 store 里保证跨服务可见，下划线前缀使其不计入业务模块概览
PACKAGE_TABLE = "_award_package"
MATERIAL_MODULE = "teach_record"

# 佐证材料引用教学档案的格式：teach_record:编号
_REF_PATTERN = re.compile(r"teach_record[:：]\s*(\d+)")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _packages() -> list[dict[str, Any]]:
    return store.rows(PACKAGE_TABLE)


def find_package(package_no: str) -> dict[str, Any] | None:
    for pkg in _packages():
        if pkg.get("包编号") == package_no:
            return pkg
    return None


def invalidate_packages_for_material(module: str, material_id: int) -> list[str]:
    """材料被注销时，把引用它的待受理包标记为已失效。

    由教学档案模块在注销档案后调用，实现"上报受理与档案注销"的冲突检测；
    已受理的包不受影响，快照保留供按原编号核验。
    """
    invalidated: list[str] = []
    for pkg in _packages():
        if pkg.get("状态") != "待受理":
            continue
        for mat in pkg.get("材料", []):
            if mat.get("模块") == module and int(mat.get("材料ID", 0)) == material_id:
                pkg["状态"] = "已失效"
                pkg["失效原因"] = (
                    f"包内{mat.get('档案类型')}《{mat.get('名称')}》(#{material_id})已被注销"
                )
                invalidated.append(str(pkg["包编号"]))
                break
    return invalidated


class TeachAwardService(BaseModuleService):
    MODULE = "teach_award"
    ENTITY = "成果申报"
    OPERATION_TERM = "初审申报"
    LIST_FIELDS = ["成果名称", "完成团队", "成果概要", "佐证材料", "申报等级", "申报日期", "审核进度", "备注说明"]
    REQUIRED_FIELDS = ["成果名称", "完成团队", "成果概要"]
    STATUS_ORDER = ["草稿", "待初审", "初审通过", "已上报"]
    ACTION_RULES = {"初审申报": "初审通过", "退回补全": "草稿", "上报评审": "已上报"}
    NEGATIVE_ACTIONS = []

    # ------------------------------------------------------------------
    # 送审材料包：导出
    # ------------------------------------------------------------------

    def export_package(self, entry_id: int) -> tuple[dict[str, Any] | None, str]:
        """从已初审成果导出证据包；同一成果重复导出返回同一个包（幂等传阅）。"""
        entry = self.get_entry(entry_id)
        if entry is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"
        if entry.get("status") != "初审通过":
            return None, (
                f"{self.ENTITY} {entry_id} 当前状态为'{entry.get('status')}'，"
                "仅初审通过的成果可导出送审材料包"
            )

        for pkg in _packages():
            if pkg.get("成果ID") == entry_id and pkg.get("状态") == "已受理":
                return None, (
                    f"{self.ENTITY} {entry_id} 已凭材料包 {pkg['包编号']} 完成受理，不可重复出包"
                )
        for pkg in _packages():
            if pkg.get("成果ID") != entry_id or pkg.get("状态") != "待受理":
                continue
            self._refresh_package(pkg)
            if pkg["状态"] == "待受理":
                return self._view(pkg), (
                    f"材料包 {pkg['包编号']} 已导出，可继续传阅，无需重复出包"
                )

        # 没有可传阅的包（首次导出，或旧包已失效需重新出包）
        refs = [int(no) for no in _REF_PATTERN.findall(str(entry.get("佐证材料") or ""))]
        if not refs:
            return None, "佐证材料未引用教学档案（格式：teach_record:编号），无法组成送审材料包"

        slots: dict[str, dict[str, Any]] = {}
        for ref_id in refs:
            material, message = self._resolve_material(ref_id)
            if material is None:
                return None, message
            slot = self._slot_of(material)
            if slot is None:
                return None, (
                    f"档案 #{ref_id} 的档案类型'{material.get('档案类型')}'"
                    "不是教案或观摩证明，不能打入材料包"
                )
            if slot in slots:
                return None, f"佐证材料引用了多份{slot}，一份材料包只装一件{slot}"
            slots[slot] = material
        missing = [name for name in ("归档教案", "观摩证明") if name not in slots]
        if missing:
            return None, f"送审材料包缺少{'、'.join(missing)}，请在佐证材料中引用对应已归档档案"

        seq = max(
            (int(str(pkg.get("包编号", "K-0")).split("-")[1]) for pkg in _packages()),
            default=0,
        ) + 1
        package = {
            "id": len(_packages()) + 1,
            "包编号": f"K-{seq}",
            "成果ID": entry_id,
            "成果名称": entry.get("成果名称"),
            "材料": [
                self._snapshot(slots["归档教案"]),
                self._snapshot(slots["观摩证明"]),
            ],
            "状态": "待受理",
            "失效原因": "",
            "导出时间": _now(),
            "受理时间": "",
        }
        _packages().append(package)
        return self._view(package), (
            f"材料包 {package['包编号']} 已导出，含归档教案与观摩证明两件材料"
        )

    # ------------------------------------------------------------------
    # 送审材料包：核验（评审员打开上报单时确认手上这份包能否受理）
    # ------------------------------------------------------------------

    def verify_package(self, package_no: str) -> tuple[dict[str, Any] | None, str]:
        pkg = find_package(package_no)
        if pkg is None:
            return None, f"材料包 {package_no} 不存在，请核对包编号"
        self._refresh_package(pkg)
        return self._view(pkg), self._tip(pkg)

    # ------------------------------------------------------------------
    # 送审材料包：凭包受理上报
    # ------------------------------------------------------------------

    def submit_with_package(
        self, entry_id: int, package_no: str
    ) -> tuple[dict[str, Any] | None, str]:
        entry = self.get_entry(entry_id)
        if entry is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"
        if not package_no:
            return None, "请提供评审员交回的材料包编号"
        pkg = find_package(package_no)
        if pkg is None:
            return None, f"材料包 {package_no} 不存在，请核对包编号"
        # 材料包绑定成果：其他成果即使使用同名教案，也不能凭这个包上报
        if int(pkg.get("成果ID", 0)) != entry_id:
            return None, (
                f"材料包 {package_no} 属于成果 #{pkg['成果ID']}《{pkg['成果名称']}》，"
                f"不能用于成果 #{entry_id} 上报；即使使用同名教案，也需为本成果另行导出材料包"
            )
        # 幂等：已受理的包不重复登记，全流程只登记一件送审成果
        if pkg["状态"] == "已受理":
            return None, f"材料包 {package_no} 已完成受理登记，无需重复上报"
        self._refresh_package(pkg)
        if pkg["状态"] == "已失效":
            return None, (
                f"材料包 {package_no} 已失效：{pkg['失效原因']}；"
                "上报受理与档案注销冲突，需补齐证明重新出包，"
                "不能以原教案搭配未确认替代证明受理"
            )
        if entry.get("status") != "初审通过":
            return None, f"{self.ENTITY} {entry_id} 必须先初审通过，才能上报"

        now = _now()
        pkg["状态"] = "已受理"
        pkg["受理时间"] = now
        entry["status"] = "已上报"
        entry["pending"] = False
        entry["abnormal"] = False
        # 成果待办登记本次受理
        entry["受理材料包"] = package_no
        entry["受理时间"] = now
        entry["审核进度"] = f"已受理送审（材料包{package_no}）"
        return entry, f"{self.ENTITY} {entry_id} 已凭材料包 {package_no} 完成受理登记并上报"

    # ------------------------------------------------------------------
    # 内部：材料解析、快照、冲突检测
    # ------------------------------------------------------------------

    @staticmethod
    def _slot_of(material: dict[str, Any]) -> str | None:
        kind = str(material.get("档案类型", ""))
        if "教案" in kind:
            return "归档教案"
        if "观摩" in kind:
            return "观摩证明"
        return None

    def _resolve_material(self, ref_id: int) -> tuple[dict[str, Any] | None, str]:
        """把佐证材料引用解析成可入包的教学档案。

        引用的档案已注销时，只允许用"同名且已归档确认"的替代材料重新出包；
        未确认的替代证明（草稿/待审核）不能拼进材料包。
        """
        material = store.find(MATERIAL_MODULE, ref_id)
        if material is None:
            return None, f"佐证材料引用的档案 #{ref_id} 不存在"
        status = material.get("status")
        if status == "已归档":
            return material, ""
        if status == "已注销":
            replacement = self._find_replacement(material)
            if replacement is not None:
                return replacement, ""
            return None, (
                f"档案 #{ref_id}（{material.get('档案类型')}《{material.get('内容摘要')}》）已注销，"
                "同名替代材料尚未归档确认，请资料员补齐证明归档后重新出包"
            )
        return None, (
            f"档案 #{ref_id}（{material.get('档案类型')}）当前状态为'{status}'，"
            "未归档确认，不能打入材料包"
        )

    @staticmethod
    def _find_replacement(cancelled: dict[str, Any]) -> dict[str, Any] | None:
        for row in store.rows(MATERIAL_MODULE):
            if int(row.get("id", 0)) == int(cancelled.get("id", 0)):
                continue
            if row.get("status") != "已归档":
                continue
            if (row.get("档案类型") == cancelled.get("档案类型")
                    and row.get("内容摘要") == cancelled.get("内容摘要")):
                return row
        return None

    @staticmethod
    def _snapshot(material: dict[str, Any]) -> dict[str, Any]:
        return {
            "模块": MATERIAL_MODULE,
            "材料ID": int(material.get("id", 0)),
            "名称": material.get("内容摘要"),
            "档案类型": material.get("档案类型"),
            "教师姓名": material.get("教师姓名"),
            "导出时状态": material.get("status"),
        }

    @staticmethod
    def _refresh_package(pkg: dict[str, Any]) -> None:
        """惰性冲突检测：待受理的包在核验/受理前复查包内材料当前状态。"""
        if pkg.get("状态") != "待受理":
            return
        for mat in pkg.get("材料", []):
            current = store.find(mat["模块"], int(mat["材料ID"]))
            if current is None or current.get("status") == "已注销":
                pkg["状态"] = "已失效"
                pkg["失效原因"] = (
                    f"包内{mat['档案类型']}《{mat['名称']}》(#{mat['材料ID']})已被注销"
                )
                return
            if current.get("status") != "已归档":
                pkg["状态"] = "已失效"
                pkg["失效原因"] = (
                    f"包内{mat['档案类型']}《{mat['名称']}》(#{mat['材料ID']})"
                    f"状态变为'{current.get('status')}'"
                )
                return

    def _tip(self, pkg: dict[str, Any]) -> str:
        status = pkg["状态"]
        if status == "待受理":
            return f"材料包 {pkg['包编号']} 材料齐全有效，可以受理上报"
        if status == "已受理":
            return (
                f"材料包 {pkg['包编号']} 已于 {pkg['受理时间']} 受理，"
                "可按原编号核验当时使用的两件材料"
            )
        return (
            f"材料包 {pkg['包编号']} 已失效：{pkg['失效原因']}；"
            "需补齐证明重新出包，不能以原教案搭配未确认替代证明受理"
        )

    def _view(self, pkg: dict[str, Any]) -> dict[str, Any]:
        return {
            "包编号": pkg["包编号"],
            "成果ID": pkg["成果ID"],
            "成果名称": pkg["成果名称"],
            "状态": pkg["状态"],
            "失效原因": pkg["失效原因"],
            "导出时间": pkg["导出时间"],
            "受理时间": pkg["受理时间"],
            "可受理": pkg["状态"] == "待受理",
            "提示": self._tip(pkg),
            "材料": [dict(mat) for mat in pkg["材料"]],
        }

    # ------------------------------------------------------------------
    # 通用动作：初审、退回；上报评审必须凭材料包走受理通道
    # ------------------------------------------------------------------

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        """执行动作，含状态约束。"""
        entry = self.get_entry(entry_id)
        if entry is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"

        # 初审申报：必须是待初审
        if action == "初审申报":
            if entry.get("status") not in ("待初审", "草稿"):
                return None, f"{self.ENTITY} {entry_id} 当前状态为'{entry.get('status')}'，不可初审"

        # 上报评审：必须先初审通过，且凭送审材料包编号走受理通道
        if action == "上报评审":
            if entry.get("status") != "初审通过":
                return None, f"{self.ENTITY} {entry_id} 必须先初审通过，才能上报"
            return None, "上报评审需凭送审材料包编号受理：请先导出证据包，再经材料包受理通道上报"

        # 退回补全：不能退回已上报的
        if action == "退回补全":
            if entry.get("status") in ("初审通过", "已上报"):
                return None, f"{self.ENTITY} {entry_id} 已经{entry.get('status')}，不可退回补全"

        return super().run_action(entry_id, action)
