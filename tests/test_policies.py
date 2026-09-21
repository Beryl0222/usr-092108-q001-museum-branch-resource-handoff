"""借调条件、异常影响范围、保障容量、讲师与运力争用的单元测试。"""

import unittest
from datetime import datetime

from src import policies as P


def venue(**kw):
    base = {"venue_id": "v", "name": "x", "status": "open",
            "env_capable_for_textile": True, "playback_ready": True,
            "latest_breach": False}
    base.update(kw)
    return base


SESSION = {"planned_start": "2026-10-03T10:00:00+08:00",
           "planned_end": "2026-10-03T11:30:00+08:00"}


class LoanPolicyTest(unittest.TestCase):
    def test_original_requires_textile_environment_insurance_escort(self) -> None:
        res = {"resource_kind": "original", "status": "available", "holds": []}
        plan = {"insurance_confirmed": True, "escort_confirmed": True}
        ok = P.evaluate_loan(res, venue(), SESSION, plan)
        self.assertTrue(ok)

        # 缺一：没有押运 → 拒批。
        d = P.evaluate_loan(res, venue(), SESSION,
                            {"insurance_confirmed": True, "escort_confirmed": False})
        self.assertFalse(d)
        self.assertIn("缺少押运人员确认", d.reasons)

        # 场地无恒温恒湿条件 → 拒批（矿区点情形）。
        d = P.evaluate_loan(res, venue(env_capable_for_textile=False), SESSION, plan)
        self.assertIn("场地不具备纺织品温湿度展陈条件", d.reasons)

        # 最近一次环境读数超标 → 即使有设备也不得调入。
        d = P.evaluate_loan(res, venue(latest_breach=True), SESSION, plan)
        self.assertIn("场地最近一次环境读数超标，真品不得调入", d.reasons)

        # 有未消除保留意见 → 拒批。
        d = P.evaluate_loan({**res, "holds": ["锦片边缘脱线"]}, venue(), SESSION, plan)
        self.assertIn("真品存在未消除的保留意见：锦片边缘脱线", d.reasons)

    def test_replica_checks_transport_fit_and_vehicle(self) -> None:
        res = {"resource_kind": "replica", "status": "available"}
        d = P.evaluate_loan(res, venue(), SESSION,
                            {"vehicle_id": "VAN-05", "transport_fit": True})
        self.assertTrue(d)
        d = P.evaluate_loan(res, venue(), SESSION,
                            {"vehicle_id": "", "transport_fit": False})
        self.assertFalse(d)
        self.assertIn("车辆装载能力不足（尺寸或重量超限）", d.reasons)
        self.assertIn("未安排运输车辆", d.reasons)
        # 复制品不要求恒温恒湿：环境不达标场馆也可借。
        d = P.evaluate_loan(res, venue(env_capable_for_textile=False), SESSION,
                            {"vehicle_id": "VAN-06", "transport_fit": True})
        self.assertTrue(d)

    def test_digital_checks_license_scope_and_expiry(self) -> None:
        res = {"resource_kind": "digital", "status": "available"}
        plan_ok = {"license_covers_venue": True,
                   "license_expires_at": "2027-12-31T23:59:59+08:00"}
        self.assertTrue(P.evaluate_loan(res, venue(), SESSION, plan_ok))

        d = P.evaluate_loan(res, venue(), SESSION,
                            {"license_covers_venue": False, **
                             {"license_expires_at": "2027-12-31T23:59:59+08:00"}})
        self.assertIn("授权范围不覆盖该分馆", d.reasons)

        d = P.evaluate_loan(res, venue(), SESSION,
                            {"license_covers_venue": True,
                             "license_expires_at": "2026-10-03T10:30:00+08:00"})
        self.assertIn("授权在场次结束前到期", d.reasons)

        d = P.evaluate_loan(res, venue(playback_ready=False), SESSION, plan_ok)
        self.assertIn("场地缺少可播放设备", d.reasons)


class ImpactScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.resources = {
            "O1": {"resource_kind": "original", "location_venue_id": "VB"},
            "R1": {"resource_kind": "replica", "location_venue_id": "VB"},
            "D1": {"resource_kind": "digital", "location_venue_id": "VM"},
        }
        self.sessions = {
            "S1": {"venue_id": "VB",
                   "planned_start": "2026-09-27T14:00:00+08:00",
                   "planned_end": "2026-09-27T15:30:00+08:00",
                   "resource_history": {"O1": "original", "R1": "replica"}},
        }
        self.transfers = {
            "T1": {"resource_ids": ["R1"]},
            "T2": {"resource_ids": ["D1"]},
        }

    def test_transfer_delay_only_impacts_late_resources_on_that_order(self) -> None:
        impacted = P.impacted_resources(
            "transfer_delay",
            {"transfer_id": "T1",
             "new_eta": "2026-09-27T15:00:00+08:00",
             "before_session_start": "2026-09-27T14:00:00+08:00"},
            self.resources, self.sessions, self.transfers)
        self.assertEqual(set(impacted), {"R1"})  # 迟到单上的复制品
        # 数字内容 D1 与真品 O1 不在迟延单上，不受影响。

        # 迟延但仍赶得上开场 → 什么都不重排。
        fine = P.impacted_resources(
            "transfer_delay",
            {"transfer_id": "T1", "new_eta": "2026-09-27T13:00:00+08:00",
             "before_session_start": "2026-09-27T14:00:00+08:00"},
            self.resources, self.sessions, self.transfers)
        self.assertEqual(fine, {})

    def test_environment_breach_recalls_only_originals_at_venue(self) -> None:
        impacted = P.impacted_resources(
            "environment_breach", {"venue_id": "VB"},
            self.resources, self.sessions, self.transfers)
        self.assertEqual(set(impacted), {"O1"})  # 只撤真品
        self.assertNotIn("R1", impacted)         # 复制品照常
        self.assertNotIn("D1", impacted)         # 数字内容照常

    def test_venue_out_of_service_impacts_only_overlapping_sessions(self) -> None:
        impacted = P.impacted_resources(
            "venue_out_of_service",
            {"venue_id": "VB",
             "from_time": "2026-09-27T00:00:00+08:00",
             "to_time": "2026-09-27T23:59:59+08:00"},
            self.resources, self.sessions, self.transfers)
        self.assertEqual(set(impacted), {"O1", "R1"})

        # 停用窗口与场次不重叠 → 不动任何资源。
        impacted = P.impacted_resources(
            "venue_out_of_service",
            {"venue_id": "VB",
             "from_time": "2026-09-28T00:00:00+08:00",
             "to_time": "2026-09-28T23:59:59+08:00"},
            self.resources, self.sessions, self.transfers)
        self.assertEqual(impacted, {})

    def test_environment_thresholds_for_textile(self) -> None:
        good = {"temp_c": 20.0, "humidity_pct": 55.0}
        self.assertTrue(P.environment_allows(good))
        self.assertFalse(P.environment_allows({"temp_c": 24.6, "humidity_pct": 65.0}))
        self.assertFalse(P.environment_allows({"temp_c": 14.0, "humidity_pct": 55.0}))


def slot(seats, assigned=None):
    return {"seats_by_pool": dict(seats),
            "assigned_by_pool": dict(assigned or {})}


class CapacityTest(unittest.TestCase):
    def test_general_booking_cannot_touch_protected_pools(self) -> None:
        s = slot({"general": 20, "children_group": 12, "mobility_access": 4},
                 {"general": 19})  # 普通只剩 1
        d = P.try_allocate(s, {"general": 5}, entitlement=())
        self.assertFalse(d)
        self.assertTrue(any("普通池余额不足" in r for r in d.reasons))

    def test_children_group_needs_entitlement(self) -> None:
        s = slot({"general": 20, "children_group": 12, "mobility_access": 4})
        # 无资格却想占儿童池 → 拒绝。
        d = P.try_allocate(s, {"children_group": 10}, entitlement=())
        self.assertIn("无权占用保障池 children_group（需相应资格）", d.reasons)
        # 有资格且池内有余 → 通过。
        d = P.try_allocate(s, {"children_group": 10}, entitlement=("children_group",))
        self.assertTrue(d)

    def test_mobility_access_needs_entitlement(self) -> None:
        s = slot({"general": 20, "children_group": 12, "mobility_access": 4})
        d = P.try_allocate(s, {"mobility_access": 2}, entitlement=())
        self.assertIn("无权占用保障池 mobility_access（需相应资格）", d.reasons)
        d = P.try_allocate(s, {"mobility_access": 2},
                           entitlement=("mobility_access",))
        self.assertTrue(d)

    def test_protected_pool_shortage_does_not_dip_into_general_or_other_pool(self) -> None:
        # 无障碍池已满：即使普通池有空也不会自动挪名额，需走显式回落。
        s = slot({"general": 20, "children_group": 12, "mobility_access": 4},
                 {"mobility_access": 4})
        d = P.try_allocate(s, {"mobility_access": 1},
                           entitlement=("mobility_access",))
        self.assertIn("保障池 mobility_access 余额不足（剩余 0）", d.reasons)

    def test_waitlist_promotion_is_per_pool_fifo(self) -> None:
        s = slot({"general": 20, "children_group": 12, "mobility_access": 4},
                 {"mobility_access": 3})  # 余 1
        entries = [
            {"waitlist_id": "W-general", "pool": "general", "seats": 1,
             "status": "waiting", "created_seq": 0},
            {"waitlist_id": "W-access", "pool": "mobility_access", "seats": 1,
             "status": "waiting", "created_seq": 1},
        ]
        promoted = P.promote_waitlist(s, entries, "mobility_access", 1)
        self.assertEqual(promoted, ["W-access"])  # 普通候补不跨池补位


class ContentionTest(unittest.TestCase):
    def test_same_vehicle_double_booked_detected(self) -> None:
        transfers = [
            {"transfer_id": "T103", "vehicle_id": "VAN-05",
             "planned_departure": "2026-09-27T07:30:00+08:00",
             "planned_arrival": "2026-09-27T13:30:00+08:00"},
            {"transfer_id": "T104", "vehicle_id": "VAN-05",
             "planned_departure": "2026-09-27T08:00:00+08:00",
             "planned_arrival": "2026-09-27T11:00:00+08:00"},
        ]
        conflicts = P.find_vehicle_conflicts(transfers)
        self.assertEqual(conflicts[0]["type"], "vehicle_double_booked")
        self.assertEqual(conflicts[0]["vehicle_id"], "VAN-05")

    def test_instructor_overlap_and_travel_gap_detected(self) -> None:
        assignments = [
            {"instructor_id": "I1", "session_id": "S1", "venue_id": "VA",
             "planned_start": "2026-09-27T10:00:00+08:00",
             "planned_end": "2026-09-27T11:30:00+08:00"},
            # 跨馆连场仅隔 30 分钟（<45 分钟路途缓冲）。
            {"instructor_id": "I1", "session_id": "S2", "venue_id": "VB",
             "planned_start": "2026-09-27T12:00:00+08:00",
             "planned_end": "2026-09-27T13:00:00+08:00"},
        ]
        conflicts = P.find_instructor_conflicts(assignments)
        self.assertTrue(any(c["type"] == "travel_gap_too_short" for c in conflicts))

        # 同馆背靠背且时间重叠 → overlap。
        assignments[1]["venue_id"] = "VA"
        assignments[1]["planned_start"] = "2026-09-27T11:00:00+08:00"
        conflicts = P.find_instructor_conflicts(assignments)
        self.assertTrue(any(c["type"] == "overlap" for c in conflicts))


if __name__ == "__main__":
    unittest.main()
