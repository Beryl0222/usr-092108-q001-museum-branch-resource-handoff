"""跨馆资源接力领域验收测试。

正向用例重放 data/sample.json 的北魏服饰复原课事件流；
反向用例用最小合成事件流验证不变量确实能拦住违规。
"""

import json
import unittest
from pathlib import Path

from src.projection import RelayProjection
from src.validator import _parse_dt, deduplicate, validate_event, validate_stream

ROOT = Path(__file__).parents[1]


def load_events() -> list[dict]:
    return json.loads((ROOT / "data" / "sample.json").read_text(encoding="utf-8"))["events"]


def ev(event_type, agg_type, agg_id, at, version, summary="合成事件", **payload) -> dict:
    e = {"event_id": f"T-{agg_id}-{version}", "event_type": event_type,
         "aggregate_type": agg_type, "aggregate_id": agg_id,
         "occurred_at": at, "version": version, "summary": summary}
    if payload:
        e["payload"] = payload
    return e


class SampleReplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.events = load_events()
        cls.proj = RelayProjection(cls.events)

    def test_no_invariant_violations_in_sample(self) -> None:
        self.assertEqual(self.proj.check_invariants(), [])

    # ── 验收一：从任何一场活动还原物品、人员、场地、异常交接 ──────────────
    def test_session_reconstructs_resources_people_venue_anomalies(self) -> None:
        view = self.proj.session_view("S-20261017-MT")
        # 场地：原明堂，实际平城
        self.assertEqual(view["original_venue"]["venue_id"], "V-MT")
        self.assertEqual(view["venue"]["venue_id"], "V-PC")
        self.assertTrue(view["relocated"])
        # 人员：沈老师先解除后平移指派，终场挂在替代场次
        self.assertIn("EDU-SHEN", [x["educator_id"] for x in view["educators"]])
        # 物品：三件复制品 + 数字内容最终落在替代场次
        final_resources = {r["resource_id"] for r in view["resources"]
                           if r["venue_id"] == "V-PC"}
        self.assertGreaterEqual(final_resources, {"R-REP-01", "R-REP-02", "R-REP-03", "D-DIG-01"})
        # 真品预约被撤回事件可还原
        self.assertTrue(any(r["type"] == "RESOURCE_RESERVATION_RELEASED"
                            and r["resource_id"] == "R-AUTH-01" for r in view["resources"]))
        # 四张运单全程在场
        self.assertEqual(view["transfers"],
                         ["T-2026-001", "T-2026-002", "T-2026-003", "T-2026-004"])
        # 三个异常根：温湿度、运输迟延、场馆停用
        roots = {self.proj.by_id[i]["event_type"] for i in view["anomaly_roots"]}
        self.assertEqual(roots, {"ENVIRONMENT_ALERT_RAISED", "TRANSFER_DELAYED",
                                 "VENUE_TAKEN_OUT_OF_SERVICE"})
        # 反馈已归档
        self.assertEqual({f["feedback_id"] for f in view["feedback"]}, {"F-001", "F-002"})

    def test_anomaly_chain_links_root_to_rearrangement(self) -> None:
        view = self.proj.session_view("S-20261017-MT")
        closure = next(i for i in view["anomaly_roots"]
                       if self.proj.by_id[i]["event_type"] == "VENUE_TAKEN_OUT_OF_SERVICE")
        chain_types = {x["event_type"] for x in self.proj.anomaly_chain(closure)}
        self.assertIn("SESSION_RELOCATED", chain_types)
        self.assertIn("SESSION_OPENED", chain_types)        # 替代场次开仓
        self.assertIn("WAITLIST_ENTRY_PROMOTED", chain_types)

    # ── 验收二：预约页面所示地点和条件与现场一致 ─────────────────────────
    def test_booking_page_shows_effective_venue_aids_and_quota(self) -> None:
        page = self.proj.booking_page("S-20261017-MT")
        self.assertTrue(page["relocated"])
        self.assertEqual(page["branch"]["venue_id"], "V-PC")
        self.assertEqual(page["replacement"]["venue_id"], "V-PC")
        # 开课时三件复制教具均已送达替代场馆
        self.assertEqual(page["teaching_aids"]["total"], 3)
        self.assertEqual(page["teaching_aids"]["arrived"], 3)
        self.assertTrue(all(i["arrived"] for i in page["teaching_aids"]["items"]))
        # 数字内容授权在场
        self.assertEqual(len(page["digital_contents"]), 1)
        # 无障碍 6 席已确认 5（含候补转正的王女士），余 1
        self.assertEqual(page["accessible_seats"],
                         {"capacity": 6, "confirmed": 5, "remaining": 1})
        # 儿童保障 12 席全部由儿童团体占用，余 0
        self.assertEqual(page["children_seats"],
                         {"capacity": 12, "confirmed": 12, "remaining": 0})

    # ── 验收三：总馆识别资源在途中、待检查、可再次使用 ───────────────────
    def test_resource_states_across_lifecycle(self) -> None:
        # 10/16 12:00：T-01 迟延在途，T-02 急运也在途
        mid_delivery = RelayProjection(
            self.events, as_of=_parse_dt("2026-10-16T12:00:00+08:00"))
        states = mid_delivery.resources_by_state()
        self.assertIn("R-REP-01", states.get("in_transit", []))
        self.assertIn("R-REP-02", states.get("in_transit", []))
        detail = mid_delivery.resource_status("R-REP-01")["detail"]
        self.assertIn("迟延", detail)

        # 10/16 12:45：急运已交接未签收 → 待检查
        handed = RelayProjection(
            self.events, as_of=_parse_dt("2026-10-16T12:45:00+08:00"))
        self.assertEqual(handed.resource_status("R-REP-02")["state"], "pending_inspection")

        # 10/17 16:38：回馆查验后，合格的可再用；系带破损的隔离待检查
        after_return = RelayProjection(
            self.events, as_of=_parse_dt("2026-10-17T16:38:00+08:00"))
        self.assertEqual(after_return.resource_status("R-REP-01")["state"], "reusable")
        self.assertEqual(after_return.resource_status("R-REP-02")["state"], "reusable")
        self.assertEqual(after_return.resource_status("R-REP-03")["state"], "pending_inspection")

        # 故事结束：破损件修复复检合格，三件复制品均可再次使用；真品与数字内容可预约/授权
        final = self.proj.resources_by_state()
        self.assertEqual(set(final.get("reusable", [])),
                         {"R-REP-01", "R-REP-02", "R-REP-03"})
        self.assertIn("R-AUTH-01", final.get("available", []))
        self.assertIn("D-DIG-01", final.get("available", []))

    # ── 验收四：温湿度异常只撤回真品 ─────────────────────────────────────
    def test_environment_alert_only_affects_authentic(self) -> None:
        at_alert = RelayProjection(
            self.events, as_of=_parse_dt("2026-10-15T14:35:00+08:00"))
        # 真品预约已撤回
        self.assertIsNone(at_alert.resources["R-AUTH-01"].reservation)
        self.assertTrue(at_alert.resources["R-AUTH-01"].quarantined)
        # 复制品与数字内容预约原样保留
        self.assertEqual(at_alert.resources["R-REP-01"].reservation["session_id"],
                         "S-20261017-MT")
        self.assertEqual(at_alert.resources["D-DIG-01"].reservation["session_id"],
                         "S-20261017-MT")
        # 顶替事件链回指温湿度根因
        view = self.proj.session_view("S-20261017-MT")
        replacement = next(r for r in view["resources"]
                           if r["resource_id"] == "R-REP-03" and r["replaces"] == "R-AUTH-01")
        self.assertIsNotNone(replacement["caused_by"])

    # ── 验收五：保障名额不被普通预约吞掉（样例时序：普通预约先到） ───────
    def test_protected_quota_survives_earlier_general_booking(self) -> None:
        # 普通研学团 9/25 确认，儿童/无障碍团体分别 9/23、9/24 确认，
        # 即使顺序互换，保障名额仍在；终场儿童 12/12、无障碍（平移扩容）5/6
        page = self.proj.booking_page("S-20261017-MT")
        self.assertGreaterEqual(page["children_seats"]["capacity"],
                                page["children_seats"]["confirmed"])
        self.assertEqual(page["children_seats"]["confirmed"], 12)
        self.assertGreaterEqual(page["accessible_seats"]["capacity"],
                                page["accessible_seats"]["confirmed"])
        # 候补晋升同样只进对应配额：王女士（无障碍候补）不占普通席
        confirmed = self.proj._confirmed_seats("S-20261017-PC")
        self.assertEqual(confirmed["accessible"], 5)
        self.assertEqual(confirmed["children"], 12)
        self.assertEqual(confirmed["general"], 2)

    # ── 验收六：离线补报开始/完成/归还各只认一次 ─────────────────────────
    def test_offline_reports_each_accepted_once(self) -> None:
        doc = json.loads((ROOT / "data" / "sample.json").read_text(encoding="utf-8"))
        raw = doc["events"] + doc["duplicate_deliveries"]
        accepted, rejected = deduplicate(raw)
        keys_accepted = [e["idempotency_key"] for e in accepted
                         if e.get("idempotency_key")]
        self.assertEqual(len(keys_accepted), len(set(keys_accepted)))
        # 开始、完成、归还三种动作各有一条被接收
        self.assertIn("S-20261017-PC#started#local-01", keys_accepted)
        self.assertIn("S-20261017-PC#completed#local-01", keys_accepted)
        self.assertIn("R-REP-01#returned#S-20261017-PC", keys_accepted)
        # 重投被丢弃，且事件数不增加
        self.assertEqual(len(accepted), len(doc["events"]))
        self.assertEqual({e["summary"] for e in rejected},
                         {"活动开始补报重投（与首条同幂等键，应丢弃）",
                          "备用教具归还补报重投（同幂等键，应丢弃）"})

    # ── 验收七：讲解更新后，旧场次还原仍指向 v1 ──────────────────────────
    def test_interpretation_update_keeps_pinned_version_of_old_session(self) -> None:
        view = self.proj.session_view("S-20261017-MT")
        self.assertEqual(view["content_pinned"]["interpretation_version"], "v1")
        self.assertEqual(view["content_pinned"]["exhibit_version"], "v1")
        self.assertEqual(view["content_pinned"]["course_material_version"], "v1")
        # v2 确实已发布
        versions = {e["aggregate_id"] for e in self.events
                    if e["event_type"] == "INTERPRETATION_PUBLISHED"}
        self.assertIn("INT-BEIWEI-V2", versions)
        # 新场次若开仓可固化 v2，旧场次不受影响（固化版本引用校验通过即证明 v1 仍在）
        self.assertEqual(self.proj.check_invariants(), [])

    # ── 验收八：替代场次闭环（容量、名额平移、讲师、教具开课前送达） ─────
    def test_replacement_session_closes_the_loop(self) -> None:
        s_old = self.proj.sessions["S-20261017-MT"]
        s_new = self.proj.sessions["S-20261017-PC"]
        self.assertEqual(s_old["replacement_session_id"], "S-20261017-PC")
        self.assertGreaterEqual(s_new["accessible_seats"], s_old["accessible_seats"])
        self.assertGreaterEqual(s_new["protected_children_seats"],
                                s_old["protected_children_seats"])
        # 平移预约全部在替代场次重新确认
        confirmed_at_new = {
            e["aggregate_id"] for e in self.events
            if e["event_type"] == "BOOKING_CONFIRMED"
            and (e.get("payload") or {}).get("session_id") == "S-20261017-PC"}
        self.assertGreaterEqual(confirmed_at_new,
                                {"B-2026-001", "B-2026-002", "B-2026-004"})


class SyntheticInvariantTest(unittest.TestCase):
    """合成最小事件流，验证不变量对违规真的报警。"""

    def _base_venue_session(self) -> list[dict]:
        return [
            ev("VENUE_REGISTERED", "venue", "V1", "2026-09-01T09:00:00+08:00", 1,
               branch_name="测试分馆", venue_id="V1"),
            ev("SESSION_OPENED", "program_session", "S1", "2026-09-02T09:00:00+08:00", 1,
               venue_id="V1", course_code="C1", capacity=10,
               scheduled_start="2026-10-01T10:00:00+08:00",
               scheduled_end="2026-10-01T11:00:00+08:00",
               protected_children_seats=4, accessible_seats=2),
        ]

    def test_quota_overuse_is_rejected(self) -> None:
        events = self._base_venue_session()
        events += [
            ev("BOOKING_CONFIRMED", "group_booking", "B1", "2026-09-03T09:00:00+08:00", 1,
               session_id="S1", seats=3, quota_class="accessible"),
            ev("BOOKING_CONFIRMED", "group_booking", "B2", "2026-09-03T09:05:00+08:00", 1,
               session_id="S1", seats=3, quota_class="accessible"),
        ]
        errors = RelayProjection(events).check_invariants()
        self.assertTrue(any("无障碍名额超用" in x for x in errors), errors)

    def test_general_booking_cannot_consume_protected_seats(self) -> None:
        events = self._base_venue_session()
        events += [
            ev("BOOKING_CONFIRMED", "group_booking", "B1", "2026-09-03T09:00:00+08:00", 1,
               session_id="S1", seats=10, quota_class="general"),
        ]
        errors = RelayProjection(events).check_invariants()
        # 普通预算 = 10-4-2 = 4
        self.assertTrue(any("普通席超用" in x for x in errors), errors)

    def test_authentic_reservation_blocked_under_active_alert(self) -> None:
        events = self._base_venue_session()
        events += [
            ev("RESOURCE_REGISTERED", "collection_resource", "R1",
               "2026-09-01T10:00:00+08:00", 1, resource_kind="authentic_object",
               home_venue_id="V1"),
            ev("RESOURCE_RESERVED", "collection_resource", "R1",
               "2026-09-02T10:00:00+08:00", 2, session_id="S1", venue_id="V1",
               resource_kind="authentic_object"),
            ev("ENVIRONMENT_ALERT_RAISED", "venue", "V1",
               "2026-09-02T11:00:00+08:00", 2, venue_id="V1"),
        ]
        errors = RelayProjection(events).check_invariants()
        self.assertTrue(any("真品在环境告警未解除" in x for x in errors), errors)

    def test_overlapping_transfer_orders_are_contention(self) -> None:
        events = [
            ev("RESOURCE_REGISTERED", "movable_replica", "RP",
               "2026-09-01T10:00:00+08:00", 1, resource_kind="replica", home_venue_id="V0"),
            ev("TRANSFER_PLANNED", "transfer_order", "T1",
               "2026-09-02T09:00:00+08:00", 1, resources=["RP"],
               from_venue_id="V0", to_venue_id="V1"),
            ev("TRANSFER_PLANNED", "transfer_order", "T2",
               "2026-09-02T09:05:00+08:00", 1, resources=["RP"],
               from_venue_id="V1", to_venue_id="V2"),
            ev("TRANSFER_DISPATCHED", "transfer_order", "T1",
               "2026-09-03T08:00:00+08:00", 2, resources=["RP"]),
            ev("TRANSFER_DISPATCHED", "transfer_order", "T2",
               "2026-09-03T09:00:00+08:00", 2, resources=["RP"]),
            ev("TRANSFER_CLOSED", "transfer_order", "T1",
               "2026-09-03T10:00:00+08:00", 3, resources=["RP"]),
            ev("TRANSFER_CLOSED", "transfer_order", "T2",
               "2026-09-03T11:00:00+08:00", 3, resources=["RP"]),
        ]
        errors = RelayProjection(events).check_invariants()
        self.assertTrue(any("运力重叠" in x for x in errors), errors)

    def test_unqualified_educator_is_rejected(self) -> None:
        events = self._base_venue_session()
        events += [
            ev("EDUCATOR_REGISTERED", "educator", "E1", "2026-09-01T10:00:00+08:00", 1,
               name="外聘讲师", qualified_courses=["OTHER"],
               qualification_valid_until="2027-01-01"),
            ev("EDUCATOR_ASSIGNED", "program_session", "S1",
               "2026-09-02T09:10:00+08:00", 2, educator_id="E1"),
        ]
        errors = RelayProjection(events).check_invariants()
        self.assertTrue(any("无课程" in x for x in errors), errors)

    def test_replacement_with_insufficient_accessible_capacity_rejected(self) -> None:
        events = self._base_venue_session()
        events += [
            ev("VENUE_REGISTERED", "venue", "V2", "2026-09-01T09:00:00+08:00", 1,
               branch_name="备用分馆", venue_id="V2"),
            ev("SESSION_RELOCATED", "program_session", "S1",
               "2026-09-20T09:00:00+08:00", 2, venue_id="V1", to_venue_id="V2",
               replacement_session_id="S2"),
            ev("SESSION_OPENED", "program_session", "S2",
               "2026-09-20T09:05:00+08:00", 1, venue_id="V2", course_code="C1",
               capacity=8, scheduled_start="2026-10-01T10:00:00+08:00",
               scheduled_end="2026-10-01T11:00:00+08:00",
               protected_children_seats=4, accessible_seats=1),
        ]
        errors = RelayProjection(events).check_invariants()
        self.assertTrue(any("替代场次无障碍容量" in x for x in errors), errors)

    def test_synthetic_stream_is_envelope_valid(self) -> None:
        events = self._base_venue_session()
        for e in events:
            self.assertEqual(validate_event(e), [])


if __name__ == "__main__":
    unittest.main()
