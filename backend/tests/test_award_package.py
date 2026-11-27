"""送审材料包业务规则测试：导出、受理、幂等、注销冲突、拼配禁止、成果绑定。"""
import pytest

from app.services.teach_award import PACKAGE_TABLE, TeachAwardService
from app.services.teach_record import TeachRecordService
from app.store import store


def clear_all():
    for name in (*store.module_names(), PACKAGE_TABLE):
        store.rows(name).clear()


def make_material(record_svc, kind, summary, archive=True):
    entry, _ = record_svc.create_entry({
        "教师姓名": "王老师",
        "档案类型": kind,
        "内容摘要": summary,
    })
    if archive:
        record_svc.run_action(entry["id"], "审核归档")
    return entry


def make_award(award_svc, plan, cert, name="智慧课堂研究"):
    entry, _ = award_svc.create_entry({
        "成果名称": name,
        "完成团队": "教学改革组",
        "成果概要": "基于数据分析的教学方法改进",
        "佐证材料": f"teach_record:{plan['id']}、teach_record:{cert['id']}",
    })
    award_svc.run_action(entry["id"], "初审申报")
    return entry


class TestAwardPackageExport:
    """导出证据包：入口条件、材料快照、传阅幂等"""

    def setup_method(self):
        clear_all()
        self.award_svc = TeachAwardService()
        self.record_svc = TeachRecordService()
        self.plan = make_material(self.record_svc, "教案", "《勾股定理》单元教案")
        self.cert = make_material(self.record_svc, "观摩证明", "《勾股定理》课堂观摩证明")

    def test_export_requires_approved_award(self):
        entry, _ = self.award_svc.create_entry({
            "成果名称": "未初审成果",
            "完成团队": "教改组",
            "成果概要": "概要",
            "佐证材料": f"teach_record:{self.plan['id']}、teach_record:{self.cert['id']}",
        })
        pkg, msg = self.award_svc.export_package(entry["id"])
        assert pkg is None
        assert "仅初审通过" in msg

    def test_export_package_snapshots_two_materials(self):
        award = make_award(self.award_svc, self.plan, self.cert)
        pkg, msg = self.award_svc.export_package(award["id"])
        assert pkg is not None
        assert pkg["包编号"] == "K-1"
        assert pkg["状态"] == "待受理"
        assert pkg["可受理"] is True
        kinds = sorted(mat["档案类型"] for mat in pkg["材料"])
        assert kinds == ["教案", "观摩证明"]
        ids = sorted(mat["材料ID"] for mat in pkg["材料"])
        assert ids == sorted([self.plan["id"], self.cert["id"]])

    def test_repeated_export_returns_same_package(self):
        award = make_award(self.award_svc, self.plan, self.cert)
        pkg1, _ = self.award_svc.export_package(award["id"])
        pkg2, msg2 = self.award_svc.export_package(award["id"])
        pkg3, _ = self.award_svc.export_package(award["id"])
        # 多次导出供传阅，始终是同一个包
        assert pkg1["包编号"] == pkg2["包编号"] == pkg3["包编号"] == "K-1"
        assert "无需重复出包" in msg2
        assert len(store.rows(PACKAGE_TABLE)) == 1

    def test_export_requires_lesson_plan_and_certificate(self):
        entry, _ = self.award_svc.create_entry({
            "成果名称": "缺证明的成果",
            "完成团队": "教改组",
            "成果概要": "概要",
            "佐证材料": f"teach_record:{self.plan['id']}",
        })
        self.award_svc.run_action(entry["id"], "初审申报")
        pkg, msg = self.award_svc.export_package(entry["id"])
        assert pkg is None
        assert "观摩证明" in msg


class TestAwardPackageSubmit:
    """凭包受理：登记、幂等、成果绑定"""

    def setup_method(self):
        clear_all()
        self.award_svc = TeachAwardService()
        self.record_svc = TeachRecordService()
        self.plan = make_material(self.record_svc, "教案", "《勾股定理》单元教案")
        self.cert = make_material(self.record_svc, "观摩证明", "《勾股定理》课堂观摩证明")
        self.award = make_award(self.award_svc, self.plan, self.cert)
        self.pkg, _ = self.award_svc.export_package(self.award["id"])

    def test_submit_registers_acceptance_on_award(self):
        entry, msg = self.award_svc.submit_with_package(self.award["id"], "K-1")
        assert entry is not None
        assert entry["status"] == "已上报"
        assert entry["pending"] is False
        # 成果待办登记本次受理
        assert entry["受理材料包"] == "K-1"
        assert entry["受理时间"]
        assert "K-1" in entry["审核进度"]
        view, _ = self.award_svc.verify_package("K-1")
        assert view["状态"] == "已受理"

    def test_duplicate_submit_registers_only_once(self):
        self.award_svc.submit_with_package(self.award["id"], "K-1")
        entry, msg = self.award_svc.submit_with_package(self.award["id"], "K-1")
        assert entry is None
        assert "无需重复上报" in msg
        accepted = [p for p in store.rows(PACKAGE_TABLE) if p["状态"] == "已受理"]
        assert len(accepted) == 1

    def test_package_bound_to_owning_award(self):
        # 另一项成果使用同名教案（同一归档教案），也不能凭 K-1 上报
        other = make_award(self.award_svc, self.plan, self.cert, name="另一项成果")
        entry, msg = self.award_svc.submit_with_package(other["id"], "K-1")
        assert entry is None
        assert "属于成果" in msg
        assert "同名教案" in msg
        assert store.find("teach_award", other["id"])["status"] == "初审通过"

    def test_unknown_package_rejected(self):
        entry, msg = self.award_svc.submit_with_package(self.award["id"], "K-99")
        assert entry is None
        assert "不存在" in msg

    def test_direct_submit_action_blocked(self):
        # 通用动作通道不能绕过材料包受理
        result, msg = self.award_svc.run_action(self.award["id"], "上报评审")
        assert result is None
        assert "材料包" in msg


class TestAwardPackageCancellationConflict:
    """注销冲突：导出后受理前资料员注销包内观摩证明"""

    def setup_method(self):
        clear_all()
        self.award_svc = TeachAwardService()
        self.record_svc = TeachRecordService()
        self.plan = make_material(self.record_svc, "教案", "《勾股定理》单元教案")
        self.cert = make_material(self.record_svc, "观摩证明", "《勾股定理》课堂观摩证明")
        self.award = make_award(self.award_svc, self.plan, self.cert)
        self.pkg, _ = self.award_svc.export_package(self.award["id"])
        # 评审员下载包 K-1 后、确认上报之前，资料员注销了包内的观摩证明
        _, self.cancel_msg = self.record_svc.run_action(self.cert["id"], "注销档案")

    def test_cancellation_marks_package_invalid(self):
        assert "K-1" in self.cancel_msg
        assert "失效" in self.cancel_msg
        view, msg = self.award_svc.verify_package("K-1")
        assert view["状态"] == "已失效"
        assert view["可受理"] is False
        assert "重新出包" in msg

    def test_submit_rejected_after_cancellation(self):
        entry, msg = self.award_svc.submit_with_package(self.award["id"], "K-1")
        assert entry is None
        assert "已失效" in msg
        assert "重新出包" in msg
        # 不能把原教案和未确认的替代证明拼一起受理
        assert "未确认替代证明" in msg
        assert store.find("teach_award", self.award["id"])["status"] == "初审通过"

    def test_unconfirmed_replacement_cannot_be_packaged(self):
        # 资料员补录了同名观摩证明，但尚未归档确认
        make_material(self.record_svc, "观摩证明", "《勾股定理》课堂观摩证明", archive=False)
        pkg, msg = self.award_svc.export_package(self.award["id"])
        assert pkg is None
        assert "尚未归档确认" in msg

    def test_reexport_after_replacement_archived(self):
        # 补齐证明：同名观摩证明归档确认后，重新出包
        replacement = make_material(self.record_svc, "观摩证明", "《勾股定理》课堂观摩证明")
        pkg, msg = self.award_svc.export_package(self.award["id"])
        assert pkg is not None
        assert pkg["包编号"] == "K-2"
        cert_ids = [m["材料ID"] for m in pkg["材料"] if m["档案类型"] == "观摩证明"]
        assert cert_ids == [replacement["id"]]
        # 旧包保持已失效，新包可受理
        old_view, _ = self.award_svc.verify_package("K-1")
        assert old_view["状态"] == "已失效"
        entry, _ = self.award_svc.submit_with_package(self.award["id"], "K-2")
        assert entry is not None
        assert entry["status"] == "已上报"

    def test_accepted_package_verifiable_by_original_number(self):
        # 另一份成果完整走通受理后，材料再被注销也不影响按原编号核验
        plan2 = make_material(self.record_svc, "教案", "《圆的面积》单元教案")
        cert2 = make_material(self.record_svc, "观摩证明", "《圆的面积》课堂观摩证明")
        award2 = make_award(self.award_svc, plan2, cert2, name="圆的面积研究")
        pkg2, _ = self.award_svc.export_package(award2["id"])
        self.award_svc.submit_with_package(award2["id"], pkg2["包编号"])
        self.record_svc.run_action(cert2["id"], "注销档案")
        view, msg = self.award_svc.verify_package(pkg2["包编号"])
        assert view["状态"] == "已受理"
        names = sorted(mat["名称"] for mat in view["材料"])
        assert names == ["《圆的面积》单元教案", "《圆的面积》课堂观摩证明"]
        assert all(mat["导出时状态"] == "已归档" for mat in view["材料"])
