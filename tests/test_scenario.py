"""北魏服饰复原课跨馆接力的端到端验收测试。

对应验收口径：
- 从任何一场活动都能还原物品、人员、场地与异常交接；
- 预约页面所示地点和条件与现场一致；
- 总馆能识别哪些资源正在途中、待检查或可再次使用；
- 温湿度异常、运输迟延、场馆停用只重排受影响资源；
- 保障名额不被平均分配吞掉；离线补报只认一次；
- 讲解改版不覆盖旧场次定版解释。
"""

import json
import unittest
from pathlib import Path

from src.replay import replay

ROOT = Path(__file__).parents[1]
EVENTS = json.loads((ROOT / "data" / "scenario_northern_wei.json").read_text("utf-8"))


class ScenarioTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.r = replay(EVENTS)

    # -- 幂等：离线补报开始/完成/归还各只认一次 -----------------------------

    def test_offline_backfill_accepted_once_each(self) -> None:
        stages = [o["stage"] for o in self.r.offline_reports]
        self.assertEqual(sorted(stages), ["completed", "returned", "started"])
        # 三个补报动作各重发一次，共 3 条被幂等挡下（event_id 不同、dedupe_key 相同）。
        self.assertEqual(len(self.r.duplicate_events), 3)
        dedupe_keys = [o["dedupe_key"] for o in self.r.offline_reports]
        self.assertEqual(len(dedupe_keys), len(set(dedupe_keys)))
        # 补报事件的业务时刻（昨天课后）与入账时刻（次日网络恢复）分别保留。
        returned = next(o for o in self.r.offline_reports if o["stage"] == "returned")
        self.assertEqual(returned["business_time"], "2026-10-03T16:00:00+08:00")
        self.assertEqual(returned["accepted_at"], "2026-10-04T08:30:00+08:00")

    # -- 从任何一场活动还原物品、人员、场地、异常交接 ------------------------

    def test_reconstruct_cancelled_session_A(self) -> None:
        v = self.r.session_view("S-2026-0926-A")
        self.assertEqual(v["status"], "cancelled")
        self.assertEqual(v["planned_venue_id"], "venue_mingtang")
        self.assertEqual(v["replaced_by"], "S-2026-0927-B")
        # 原场预约过的三类资源仍可还原，且定版解释停留在 v1。
        kinds = {x["resource_id"]: x["resource_kind"] for x in v["resources"]}
        self.assertEqual(kinds["O-TEX-07"], "original")
        self.assertEqual(kinds["R-COSTUME-01"], "replica")
        self.assertEqual(kinds["D-MEDIA-03"], "digital")
        self.assertEqual(v["content_lock"]["interpretation_version_id"], "interp-nw-v1")
        self.assertEqual(v["instructor"]["instructor_id"], "I-LIN-01")
        self.assertEqual(v["instructor"]["qualification_version"], "qual-2026.03")
        # 闭馆异常可追溯。
        self.assertTrue(any(a.get("kind") == "venue_out_of_service"
                            for a in v["anomalies"]))

    def test_reconstruct_delivered_session_B(self) -> None:
        v = self.r.session_view("S-2026-0927-B")
        self.assertEqual(v["status"], "delivered")
        self.assertEqual(v["actual_venue_id"], "venue_beichao")
        self.assertEqual(v["venue"]["name"], "北朝艺术分馆")
        self.assertEqual(v["replaces"], "S-2026-0926-A")
        # 讲师及其当时采用的资历版本。
        self.assertEqual(v["instructor"]["name"], "林砚")
        self.assertEqual(v["instructor"]["qualification_version"], "qual-2026.03")
        # 物品：真品被撤出、总馆套迟到、常备套顶上、数字内容照常；
        # 四件都在可还原清单里，并标明最终是否在场。
        final = {x["resource_id"]: x["in_final_plan"] for x in v["resources"]}
        self.assertFalse(final["O-TEX-07"])      # 温湿度异常撤出
        self.assertFalse(final["R-COSTUME-01"])  # 运输迟延，课后才到
        self.assertTrue(final["R-COSTUME-02"])   # 北朝馆常备套顶上
        self.assertTrue(final["D-MEDIA-03"])     # 数字内容不受任何异常影响
        # 两次异常重排，触发事件都可追溯。
        self.assertEqual(len(v["replans"]), 2)
        trigger_ids = {rep["trigger_event_id"] for rep in v["replans"]}
        self.assertEqual(len(trigger_ids), 2)
        # 运输与交接留痕（出库、入库两次以上双人交接）。
        transfer_ids = {t["transfer_id"] for t in v["transfers"]}
        self.assertIn("T-102", transfer_ids)  # 真品明堂→北朝短驳
        self.assertIn("T-104", transfer_ids)  # 复制品迟延单
        self.assertGreaterEqual(len(v["handovers"]), 2)
        self.assertTrue(all(h["condition_check_passed"] for h in v["handovers"]))
        # 反馈随场次可还原。
        roles = {f["author_role"] for f in v["feedback"]}
        self.assertEqual(roles, {"带队老师", "讲师"})

    def test_reconstruct_session_C_uses_second_trip_of_replica(self) -> None:
        v = self.r.session_view("S-2026-1003-C")
        self.assertEqual(v["venue"]["name"], "矿区研学服务点")
        self.assertEqual(v["resources"][0]["resource_id"], "R-COSTUME-01")
        # 矿区场不具备真品条件：借调被拒的记录留在借调台账。
        loan = self.r.loans["L-C-ORIG"]
        self.assertEqual(loan["status"], "rejected")
        self.assertIn("场地不具备纺织品温湿度展陈条件", loan["reasons"])

    # -- 讲解更新不改写旧场次定版 -------------------------------------------

    def test_interpretation_versions_are_point_in_time(self) -> None:
        vB = self.r.session_view("S-2026-0927-B")
        vC = self.r.session_view("S-2026-1003-C")
        self.assertEqual(vB["content_lock"]["interpretation_version_id"], "interp-nw-v1")
        self.assertEqual(vC["content_lock"]["interpretation_version_id"], "interp-nw-v2")
        # 旧场次看到的解释文本仍是 v1（风帽说），不会被 v2（御寒说）覆盖。
        self.assertIn("风帽", vB["content_lock"]["interpretation_snapshot"]["excerpt"])
        self.assertIn("御寒", vC["content_lock"]["interpretation_snapshot"]["excerpt"])
        locked_at_B = vB["content_lock"]["interpretation_snapshot"]["published_at"]
        self.assertLess(locked_at_B, "2026-09-29T10:00:00+08:00")

    # -- 预约页所示地点、教具到达、条件、名额与现场一致 ----------------------

    def test_booking_page_for_original_session_before_closure(self) -> None:
        # 9/24 真品已运抵明堂、闭馆尚未发生；页面所示与现场一致。
        early = replay(EVENTS, as_of="2026-09-24T18:00:00+08:00")
        page = early.booking_page("S-2026-0926-A")
        self.assertEqual(page["venue_name"], "明堂遗址分馆")
        self.assertEqual(page["venue_status"], "open")
        self.assertTrue(page["accessible_entrance"])
        by_id = {a["resource_id"]: a for a in page["teaching_aids"]}
        self.assertTrue(by_id["O-TEX-07"]["arrived"])       # 已押运到馆
        self.assertFalse(by_id["R-COSTUME-01"]["arrived"])  # 复制品尚未发运
        self.assertTrue(by_id["D-MEDIA-03"]["arrived"])     # 数字授权就绪
        # 儿童12已满；无障碍实际占用2（团体1+候补补位1），普通只剩2。
        self.assertEqual(page["remaining_seats_by_pool"]["children_group"], 0)
        self.assertEqual(page["remaining_seats_by_pool"]["mobility_access"], 2)
        self.assertEqual(page["remaining_seats_by_pool"]["general"], 2)
        self.assertEqual(page["mobility_access_remaining"], 2)

    def test_booking_page_shows_closure_then_replacement(self) -> None:
        # 闭馆公告刚发布、替代场尚未排好时，页面必须如实反映原场取消。
        gap = replay(EVENTS, as_of="2026-09-25T08:06:00+08:00")
        page_a = gap.booking_page("S-2026-0926-A")
        self.assertEqual(page_a["venue_status"], "out_of_service")
        self.assertEqual(page_a["session_status"], "cancelled")
        self.assertNotIn("S-2026-0927-B", gap.sessions)

        # 最终替代场页面。
        page = self.r.booking_page("S-2026-0927-B")
        self.assertEqual(page["venue_name"], "北朝艺术分馆")
        self.assertTrue(any("替代场次" in c for c in page["conditions"]))
        by_id = {a["resource_id"]: a for a in page["teaching_aids"]}
        self.assertTrue(by_id["R-COSTUME-02"]["arrived"])        # 常备套已在场
        self.assertTrue(by_id["D-MEDIA-03"]["arrived"])          # 授权就绪
        self.assertFalse(by_id["O-TEX-07"]["in_final_plan"])     # 真品已撤出
        self.assertIn("本场不使用", by_id["O-TEX-07"]["arrival_status"])
        self.assertFalse(by_id["R-COSTUME-01"]["in_final_plan"]) # 迟到、未用于本场
        # 名额随替代场迁移后：保障池账独立保留。
        self.assertEqual(page["remaining_seats_by_pool"],
                         {"general": 2, "children_group": 0, "mobility_access": 2})

    # -- 保障名额不被普通预约吞掉、候补按池 FIFO ----------------------------

    def test_protected_pools_survive_overbooking(self) -> None:
        # 超额普通预约被明确拒绝。
        self.assertEqual(self.r.bookings["G-AGENT-03"]["status"], "rejected")
        slot_b = next(s for s in self.r.slots.values()
                      if s["session_id"] == "S-2026-0927-B")
        # 保障池占用随迁移完整到达，没有被普通预约平分：儿童 12、无障碍 2。
        self.assertEqual(slot_b["assigned_by_pool"]["children_group"], 12)
        self.assertEqual(slot_b["assigned_by_pool"]["mobility_access"], 2)
        # 张女士的无障碍候补被补位；李先生的普通候补未被跨池晋升，场后失效。
        self.assertEqual(self.r.waitlists["W-ZHANG-01"]["status"], "promoted")
        self.assertEqual(self.r.waitlists["W-LI-02"]["status"], "expired")

    # -- 总馆台账：在途中 / 待检查 / 可再次使用 -----------------------------

    def test_headquarters_board_in_transit(self) -> None:
        mid = replay(EVENTS, as_of="2026-09-27T08:40:00+08:00")
        ids = {x["resource_id"] for x in mid.headquarters_board()["in_transit"]}
        self.assertIn("O-TEX-07", ids)       # 明堂→北朝短驳途中
        self.assertIn("R-COSTUME-01", ids)   # VAN-05 运输途中

    def test_headquarters_board_pending_inspection(self) -> None:
        waiting = replay(EVENTS, as_of="2026-09-28T09:30:00+08:00")
        ids = {x["resource_id"] for x in waiting.headquarters_board()["pending_inspection"]}
        self.assertEqual(ids, {"O-TEX-07"})  # 提前归还、尚未检查

    def test_headquarters_board_reusable_after_inspection(self) -> None:
        ids = {x["resource_id"] for x in self.r.headquarters_board()["reusable"]}
        self.assertIn("O-TEX-07", ids)       # 检查通过
        self.assertIn("R-COSTUME-01", ids)   # 离线补报归还+运回检查通过
        self.assertIn("R-COSTUME-02", ids)   # 常备套
        self.assertNotIn("O-TEX-07",
                         {x["resource_id"] for x in self.r.headquarters_board()["in_transit"]})

    # -- 异常交接端到端：资源时间线可追 --------------------------------------

    def test_resource_trace_tells_full_story(self) -> None:
        notes = " ".join(step["note"] for step in self.r.resource_trace("O-TEX-07"))
        self.assertIn("预留给场次 S-2026-0926-A", notes)
        self.assertIn("装车发运", notes)
        self.assertIn("召回", notes)
        self.assertIn("归还", notes)
        self.assertIn("归还检查：pass", notes)
        event_types = {step["event_type"] for step in self.r.resource_trace("O-TEX-07")}
        self.assertIn("TRANSFER_DISPATCHED", event_types)
        self.assertIn("RETURN_INSPECTED", event_types)


if __name__ == "__main__":
    unittest.main()
