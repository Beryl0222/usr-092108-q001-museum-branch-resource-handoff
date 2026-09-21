#!/usr/bin/env python3
"""生成“北魏服饰复原课”跨馆资源接力的联调样例事件流。

覆盖验收主线：
1. 带队老师预约页关心的四件事：哪座分馆、教具是否到、无障碍名额、闭馆替代场；
2. 真品/复制品/数字内容按各自条件借调（保险押运+温湿度 / 车辆装载 / 授权）；
3. 临时闭馆 → 替代场次承接，名额按池迁移、讲解版本当时定版；
4. 运输迟延只换受影响的复制品（数字内容与真品不动）；
5. 温湿度异常只撤出真品，复制品与数字内容照常上课；
6. 儿童团体、无障碍保障名额独立记账，超额普通预约被拒且不吞保障池；
7. 分馆离线补报开始/完成/归还，重复补报（同一 dedupe_key）只认一次；
8. 讲解内容改版后，旧场次仍能还原当时采用的解释；
9. 总馆台账识别：在途中、待检查、可再次使用。

运行：python3 -m tools.build_scenario
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

COURSE = "course_nw_costume"


class Builder:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self._seq = 0
        self._versions: dict[str, int] = {}

    def add(self, event_type: str, aggregate_type: str, aggregate_id: str,
            occurred_at: str, summary: str, payload: dict | None = None,
            *, dedupe_key: str | None = None, branch_id: str | None = None,
            source: str | None = None) -> dict:
        self._seq += 1
        ver = self._versions[aggregate_id] = self._versions.get(aggregate_id, 0) + 1
        event: dict = {
            "event_id": f"NW2026-{self._seq:04d}",
            "event_type": event_type,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "occurred_at": occurred_at,
            "version": ver,
            "summary": summary,
            "payload": payload or {},
        }
        if dedupe_key:
            event["dedupe_key"] = dedupe_key
        if branch_id:
            event["branch_id"] = branch_id
        if source:
            event["source"] = source
        self.events.append(event)
        return event

    def resend(self, event: dict) -> dict:
        """分馆网络恢复后重复投递同一补报（dedupe_key 相同、event_id 不同）。"""
        clone = dict(event)
        clone["payload"] = dict(event["payload"])
        self._seq += 1
        clone["event_id"] = f"NW2026-{self._seq:04d}"
        self.events.append(clone)
        return clone


def build() -> list[dict]:
    b = Builder()
    T = "2026-09-{day:02d}T{hm}:00+08:00"
    def t(day: int, hm: str) -> str:
        return T.format(day=day, hm=hm)

    # ===== 1. 分馆建档（九座分馆中的参与场馆）=============================
    b.add("VENUE_REGISTERED", "venue", "venue_main", t(1, "09:00"),
          "大同市博物馆总馆（御东）建档",
          {"venue_id": "venue_main", "name": "大同市博物馆总馆",
           "accessible_entrance": True, "env_capable_for_textile": True,
           "playback_ready": True})
    b.add("VENUE_REGISTERED", "venue", "venue_mingtang", t(1, "09:05"),
          "明堂遗址分馆建档",
          {"venue_id": "venue_mingtang", "name": "明堂遗址分馆",
           "accessible_entrance": True, "env_capable_for_textile": True,
           "playback_ready": True})
    b.add("VENUE_REGISTERED", "venue", "venue_beichao", t(1, "09:10"),
          "北朝艺术分馆建档",
          {"venue_id": "venue_beichao", "name": "北朝艺术分馆",
           "accessible_entrance": True, "env_capable_for_textile": True,
           "playback_ready": True})
    b.add("VENUE_REGISTERED", "venue", "venue_kuangqu", t(1, "09:15"),
          "矿区研学服务点建档（无恒温恒湿条件）",
          {"venue_id": "venue_kuangqu", "name": "矿区研学服务点",
           "accessible_entrance": False, "env_capable_for_textile": False,
           "playback_ready": True})

    # ===== 2. 资源建档：真品 / 复制品 / 数字内容 ===========================
    b.add("RESOURCE_REGISTERED", "collection_object", "O-TEX-07", t(2, "10:00"),
          "北魏忍冬纹锦残片（纺织品真品）建档",
          {"resource_id": "O-TEX-07", "resource_kind": "original",
           "title": "北魏忍冬纹锦残片", "home_venue_id": "venue_main"})
    b.add("CONDITION_RECORDED", "collection_object", "O-TEX-07", t(2, "10:30"),
          "真品出库前状况检查：无病害",
          {"resource_id": "O-TEX-07", "recorded_at": t(2, "10:30"),
           "holds": [], "assessment": "状况稳定，符合借展条件"})

    b.add("RESOURCE_REGISTERED", "replica", "R-COSTUME-01", t(2, "11:00"),
          "可触摸复制教具：鲜卑垂裙幅冠全套（总馆套）",
          {"resource_id": "R-COSTUME-01", "resource_kind": "replica",
           "title": "鲜卑垂裙幅冠复制品·总馆套", "home_venue_id": "venue_main"})
    b.add("RESOURCE_REGISTERED", "replica", "R-COSTUME-02", t(2, "11:05"),
          "可触摸复制教具：鲜卑垂裙幅冠全套（北朝分馆常备套）",
          {"resource_id": "R-COSTUME-02", "resource_kind": "replica",
           "title": "鲜卑垂裙幅冠复制品·北朝分馆套", "home_venue_id": "venue_beichao"})

    b.add("RESOURCE_REGISTERED", "replica", "R-PANEL-88", t(2, "11:10"),
          "巡展展板支架（城墙分馆借展中常用）",
          {"resource_id": "R-PANEL-88", "resource_kind": "replica",
           "title": "巡展展板支架一套", "home_venue_id": "venue_main"})
    b.add("RESOURCE_REGISTERED", "digital_content", "D-MEDIA-03", t(2, "14:00"),
          "数字内容：北魏服饰穿戴互动程序",
          {"resource_id": "D-MEDIA-03", "resource_kind": "digital",
           "title": "北魏服饰穿戴互动程序 v3", "home_venue_id": "venue_main"})

    # ===== 3. 讲解解释 / 材料 / 展陈版本（v1）==============================
    b.add("INTERPRETATION_VERSION_PUBLISHED", "course_material", "interp-nw-v1",
          t(3, "09:00"), "讲解解释 v1 发布：垂裙幅冠“风帽遮挡说”",
          {"version_id": "interp-nw-v1", "course_id": COURSE,
           "title": "北魏服饰讲解解释 v1",
           "excerpt": "垂裙幅冠两侧垂裙旧解为骑马驰骋时遮挡风沙的风帽。"})
    b.add("MATERIAL_VERSION_PUBLISHED", "course_material", "material-nw-v1",
          t(3, "09:10"), "课程材料 v1 发布",
          {"version_id": "material-nw-v1", "course_id": COURSE,
           "title": "北魏服饰复原课材料包 v1",
           "excerpt": "含穿戴步骤卡 6 张、织物样本观察页 1 份。"})
    b.add("EXHIBIT_VERSION_PUBLISHED", "exhibit_version", "exhibit-nw-v1",
          t(3, "09:20"), "展陈版本 v1 发布",
          {"version_id": "exhibit-nw-v1",
           "title": "“魏衣·垂裙”展陈 v1（明堂版动线）",
           "excerpt": "明堂分馆动线：展柜—触摸桌—穿戴体验区。"})

    # ===== 4. 讲师资历 =====================================================
    b.add("INSTRUCTOR_REGISTERED", "instructor", "I-LIN-01", t(3, "10:00"),
          "讲师林砚登记",
          {"instructor_id": "I-LIN-01", "name": "林砚",
           "qualifications": ["北魏服饰专题", "纺织品文物导览", "研学团带队"]})

    # ===== 5. 场次 A：9/26 上午 明堂分馆（后因闭馆被替代）==================
    b.add("SESSION_OPENED", "activity_session", "S-2026-0926-A", t(5, "09:00"),
          "北魏服饰复原课·明堂分馆场开放预约",
          {"session_id": "S-2026-0926-A", "course_id": COURSE,
           "title": "北魏服饰复原课", "venue_id": "venue_mingtang",
           "planned_start": t(26, "10:00"), "planned_end": t(26, "11:30")})
    b.add("VENUE_CAPACITY_DEFINED", "venue_slot", "slot-A", t(5, "09:05"),
          "明堂场容量建档：普通20/儿童团体12/无障碍4",
          {"slot_id": "slot-A", "venue_id": "venue_mingtang",
           "session_id": "S-2026-0926-A",
           "seats_by_pool": {"general": 20, "children_group": 12,
                             "mobility_access": 4}})
    b.add("SESSION_CONTENT_LOCKED", "activity_session", "S-2026-0926-A",
          t(5, "09:10"), "明堂场定版：讲解/材料/展陈均锁定 v1",
          {"session_id": "S-2026-0926-A",
           "interpretation_version_id": "interp-nw-v1",
           "material_version_id": "material-nw-v1",
           "exhibit_version_id": "exhibit-nw-v1"})
    b.add("INSTRUCTOR_ASSIGNED", "instructor", "I-LIN-01", t(5, "09:15"),
          "林砚承担明堂场（凭 2026.03 版资历）",
          {"instructor_id": "I-LIN-01", "session_id": "S-2026-0926-A",
           "qualification_version": "qual-2026.03"})

    # 三类资源对场次 A 的借调申请与批准（条件各异）
    b.add("LOAN_REQUESTED", "loan_request", "L-A-ORIG", t(5, "09:30"),
          "申请真品忍冬纹锦残片赴明堂场",
          {"loan_id": "L-A-ORIG", "resource_id": "O-TEX-07",
           "resource_kind": "original", "session_id": "S-2026-0926-A",
           "requested_by": "venue_mingtang"})
    b.add("LOAN_APPROVED", "loan_request", "L-A-ORIG", t(5, "10:00"),
          "真品借调批准：保险、押运、温湿度条件齐备",
          {"loan_id": "L-A-ORIG", "resource_id": "O-TEX-07",
           "session_id": "S-2026-0926-A",
           "conditions": {"insurance_confirmed": True, "escort_confirmed": True,
                          "temp_range": [15, 22], "humidity_range": [50, 60]}})
    b.add("LOAN_REQUESTED", "loan_request", "L-A-REP", t(5, "09:32"),
          "申请复制教具总馆套赴明堂场",
          {"loan_id": "L-A-REP", "resource_id": "R-COSTUME-01",
           "resource_kind": "replica", "session_id": "S-2026-0926-A",
           "requested_by": "venue_mingtang"})
    b.add("LOAN_APPROVED", "loan_request", "L-A-REP", t(5, "10:05"),
          "复制品借调批准：车辆装载匹配",
          {"loan_id": "L-A-REP", "resource_id": "R-COSTUME-01",
           "session_id": "S-2026-0926-A",
           "conditions": {"vehicle_id": "VAN-02", "transport_fit": True}})
    b.add("LOAN_REQUESTED", "loan_request", "L-A-DIG", t(5, "09:34"),
          "申请互动程序数字授权至明堂场",
          {"loan_id": "L-A-DIG", "resource_id": "D-MEDIA-03",
           "resource_kind": "digital", "session_id": "S-2026-0926-A",
           "requested_by": "venue_mingtang"})
    b.add("LOAN_APPROVED", "loan_request", "L-A-DIG", t(5, "10:10"),
          "数字授权批准：覆盖明堂分馆且授权期在场次之后",
          {"loan_id": "L-A-DIG", "resource_id": "D-MEDIA-03",
           "session_id": "S-2026-0926-A",
           "conditions": {"license_covers_venue": True,
                          "license_expires_at": "2027-12-31T23:59:59+08:00"}})
    b.add("RESOURCE_RESERVED", "collection_object", "O-TEX-07", t(5, "10:15"),
          "真品预留给明堂场", {"resource_id": "O-TEX-07", "session_id": "S-2026-0926-A"})
    b.add("RESOURCE_RESERVED", "replica", "R-COSTUME-01", t(5, "10:16"),
          "复制品总馆套预留给明堂场",
          {"resource_id": "R-COSTUME-01", "session_id": "S-2026-0926-A"})
    b.add("RESOURCE_RESERVED", "digital_content", "D-MEDIA-03", t(5, "10:17"),
          "互动程序授权预留给明堂场",
          {"resource_id": "D-MEDIA-03", "session_id": "S-2026-0926-A"})

    # ===== 6. 团体预约 / 散客候补：保障池独立记账 ===========================
    b.add("GROUP_BOOKING_REQUESTED", "group_booking", "G-SCHOOL-01", t(6, "08:30"),
          "平城路小学三年级团体预约 30 人",
          {"booking_id": "G-SCHOOL-01", "session_id": "S-2026-0926-A",
           "group_name": "平城路小学三年级研学团",
           "seats_by_pool": {"children_group": 12, "general": 18},
           "entitlements": ["children_group"]})
    b.add("GROUP_BOOKING_ACCEPTED", "group_booking", "G-SCHOOL-01", t(6, "08:35"),
          "儿童团体预约接受：儿童池12、普通池18",
          {"booking_id": "G-SCHOOL-01", "session_id": "S-2026-0926-A",
           "seats_by_pool": {"children_group": 12, "general": 18}})
    b.add("CAPACITY_ALLOCATED", "venue_slot", "slot-A", t(6, "08:36"),
          "分配儿童团体保障名额12",
          {"slot_id": "slot-A", "session_id": "S-2026-0926-A",
           "pool": "children_group", "seats": 12, "booking_id": "G-SCHOOL-01"})
    b.add("CAPACITY_ALLOCATED", "venue_slot", "slot-A", t(6, "08:37"),
          "分配普通名额18",
          {"slot_id": "slot-A", "session_id": "S-2026-0926-A",
           "pool": "general", "seats": 18, "booking_id": "G-SCHOOL-01"})

    b.add("GROUP_BOOKING_REQUESTED", "group_booking", "G-CARE-02", t(6, "09:00"),
          "康养中心轮椅体验组预约无障碍名额2",
          {"booking_id": "G-CARE-02", "session_id": "S-2026-0926-A",
           "group_name": "平城康养中心体验组",
           "seats_by_pool": {"mobility_access": 2},
           "entitlements": ["mobility_access"]})
    b.add("GROUP_BOOKING_ACCEPTED", "group_booking", "G-CARE-02", t(6, "09:05"),
          "无障碍保障名额2接受",
          {"booking_id": "G-CARE-02", "session_id": "S-2026-0926-A",
           "seats_by_pool": {"mobility_access": 2}})
    b.add("CAPACITY_ALLOCATED", "venue_slot", "slot-A", t(6, "09:06"),
          "分配无障碍保障名额2",
          {"slot_id": "slot-A", "session_id": "S-2026-0926-A",
           "pool": "mobility_access", "seats": 2, "booking_id": "G-CARE-02"})

    # 散客候补：1 个无障碍名额、2 个普通名额
    b.add("WAITLIST_ENTRY_CREATED", "waitlist_entry", "W-ZHANG-01", t(6, "12:00"),
          "散客张女士（行动不便）候补无障碍名额1",
          {"waitlist_id": "W-ZHANG-01", "session_id": "S-2026-0926-A",
           "visitor_name": "张女士", "pool": "mobility_access", "seats": 1})
    b.add("WAITLIST_ENTRY_CREATED", "waitlist_entry", "W-LI-02", t(6, "12:10"),
          "散客李先生候补普通名额2",
          {"waitlist_id": "W-LI-02", "session_id": "S-2026-0926-A",
           "visitor_name": "李先生一家", "pool": "general", "seats": 2})

    # 超额普通预约：普通池只剩 2，却申请 10；拒绝且不得挪用保障池
    b.add("GROUP_BOOKING_REQUESTED", "group_booking", "G-AGENT-03", t(7, "10:00"),
          "某机构临时申请普通名额10",
          {"booking_id": "G-AGENT-03", "session_id": "S-2026-0926-A",
           "group_name": "某机构观摩团",
           "seats_by_pool": {"general": 10}, "entitlements": []})
    b.add("GROUP_BOOKING_REJECTED", "group_booking", "G-AGENT-03", t(7, "10:02"),
          "超额预约拒绝：普通池仅余2，不得占用儿童/无障碍保障名额",
          {"booking_id": "G-AGENT-03", "session_id": "S-2026-0926-A",
           "reasons": ["普通池余额不足（剩余 2）",
                       "不得占用儿童/无障碍保障名额"]})

    # 康养中心释放 1 个无障碍名额 → 张女士按池 FIFO 补位
    b.add("CAPACITY_RELEASED", "venue_slot", "slot-A", t(8, "09:00"),
          "康养中心因一人发烧释放无障碍名额1",
          {"slot_id": "slot-A", "session_id": "S-2026-0926-A",
           "pool": "mobility_access", "seats": 1, "booking_id": "G-CARE-02"})
    b.add("WAITLIST_PROMOTED", "waitlist_entry", "W-ZHANG-01", t(8, "09:05"),
          "张女士候补补位成功（普通候补李先生不受影响）",
          {"waitlist_id": "W-ZHANG-01", "session_id": "S-2026-0926-A",
           "seats_by_pool": {"mobility_access": 1}})
    b.add("CAPACITY_ALLOCATED", "venue_slot", "slot-A", t(8, "09:06"),
          "补位占用无障碍名额1",
          {"slot_id": "slot-A", "session_id": "S-2026-0926-A",
           "pool": "mobility_access", "seats": 1, "booking_id": "W-ZHANG-01"})

    # ===== 7. 真品先行运抵明堂，交接留痕 ===================================
    b.add("TRANSFER_DISPATCHED", "transfer_order", "T-101", t(24, "09:00"),
          "真品由总柜装车，押运赴明堂分馆",
          {"transfer_id": "T-101", "resource_ids": ["O-TEX-07"],
           "from_venue_id": "venue_main", "to_venue_id": "venue_mingtang",
           "planned_departure": t(24, "09:00"), "planned_arrival": t(24, "10:30"),
           "vehicle_id": "VAN-02", "session_id": "S-2026-0926-A"})
    b.add("TRANSFER_HANDOVER", "transfer_order", "T-101", t(24, "09:05"),
          "总馆出库交接：押运员与馆员双人签字，包装状况合格",
          {"transfer_id": "T-101", "stage": "outbound_vault",
           "resource_ids": ["O-TEX-07"], "from_party": "总馆藏品库",
           "to_party": "押运组赵师傅", "condition_check_passed": True,
           "at": t(24, "09:05")})
    b.add("TRANSFER_COMPLETED", "transfer_order", "T-101", t(24, "10:40"),
          "真品送达明堂分馆并入库",
          {"transfer_id": "T-101", "resource_ids": ["O-TEX-07"],
           "arrived_at": t(24, "10:40")})
    b.add("TRANSFER_HANDOVER", "transfer_order", "T-101", t(24, "10:45"),
          "明堂分馆接收入柜，温湿度记录正常",
          {"transfer_id": "T-101", "stage": "inbound_vault",
           "resource_ids": ["O-TEX-07"], "from_party": "押运组赵师傅",
           "to_party": "明堂分馆库房", "condition_check_passed": True,
           "at": t(24, "10:45")})

    # ===== 8. 明堂分馆 9/25 临时闭馆 → 替代场次 B 落到北朝艺术分馆 ==========
    b.add("VENUE_TAKEN_OUT_OF_SERVICE", "venue", "venue_mingtang", t(25, "08:00"),
          "明堂分馆消防检修，9/26 全天临时闭馆",
          {"venue_id": "venue_mingtang", "reason": "消防设备突发检修",
           "from_time": t(26, "00:00"), "to_time": t(26, "23:59")})
    b.add("SESSION_CANCELLED", "activity_session", "S-2026-0926-A", t(25, "08:05"),
          "明堂场取消，由替代场 S-2026-0927-B 承接",
          {"session_id": "S-2026-0926-A",
           "reason": "明堂分馆临时闭馆，改至北朝艺术分馆替代场"})
    b.add("SESSION_REPLACEMENT_CREATED", "activity_session", "S-2026-0927-B",
          t(25, "08:30"),
          "为明堂场建立替代场：9/27 下午北朝艺术分馆",
          {"session_id": "S-2026-0927-B", "replaces_session_id": "S-2026-0926-A",
           "venue_id": "venue_beichao",
           "planned_start": t(27, "14:00"), "planned_end": t(27, "15:30")})
    b.add("VENUE_CAPACITY_DEFINED", "venue_slot", "slot-B", t(25, "08:35"),
          "北朝场容量与原场一致：普通20/儿童12/无障碍4",
          {"slot_id": "slot-B", "venue_id": "venue_beichao",
           "session_id": "S-2026-0927-B",
           "seats_by_pool": {"general": 20, "children_group": 12,
                             "mobility_access": 4}})
    b.add("QUOTA_TRANSFERRED", "activity_session", "S-2026-0927-B", t(25, "08:40"),
          "原场名额按池整体迁移至替代场（不跨池、不平均）",
          {"from_session_id": "S-2026-0926-A", "to_session_id": "S-2026-0927-B",
           "pools": [{"pool": "children_group", "seats": 12},
                     {"pool": "general", "seats": 18},
                     {"pool": "mobility_access", "seats": 2}]})
    b.add("SESSION_CONTENT_LOCKED", "activity_session", "S-2026-0927-B",
          t(25, "08:45"), "替代场沿用当时最新定版 v1",
          {"session_id": "S-2026-0927-B",
           "interpretation_version_id": "interp-nw-v1",
           "material_version_id": "material-nw-v1",
           "exhibit_version_id": "exhibit-nw-v1"})
    b.add("INSTRUCTOR_ASSIGNED", "instructor", "I-LIN-01", t(25, "08:50"),
          "林砚继续承担替代场",
          {"instructor_id": "I-LIN-01", "session_id": "S-2026-0927-B",
           "qualification_version": "qual-2026.03"})

    # 替代场借调：真品改由明堂短驳、数字授权追加覆盖北朝、复制品重新派车
    b.add("LOAN_REQUESTED", "loan_request", "L-B-ORIG", t(25, "09:00"),
          "真品借调改至北朝场",
          {"loan_id": "L-B-ORIG", "resource_id": "O-TEX-07",
           "resource_kind": "original", "session_id": "S-2026-0927-B",
           "requested_by": "venue_beichao"})
    b.add("LOAN_APPROVED", "loan_request", "L-B-ORIG", t(25, "09:05"),
          "真品改址批准：北朝馆恒湿条件达标、保险押运延续",
          {"loan_id": "L-B-ORIG", "resource_id": "O-TEX-07",
           "session_id": "S-2026-0927-B",
           "conditions": {"insurance_confirmed": True, "escort_confirmed": True,
                          "temp_range": [15, 22], "humidity_range": [50, 60]}})
    b.add("LOAN_REQUESTED", "loan_request", "L-B-DIG", t(25, "09:10"),
          "互动程序授权追加北朝分馆",
          {"loan_id": "L-B-DIG", "resource_id": "D-MEDIA-03",
           "resource_kind": "digital", "session_id": "S-2026-0927-B",
           "requested_by": "venue_beichao"})
    b.add("LOAN_APPROVED", "loan_request", "L-B-DIG", t(25, "09:12"),
          "数字授权批准覆盖北朝分馆",
          {"loan_id": "L-B-DIG", "resource_id": "D-MEDIA-03",
           "session_id": "S-2026-0927-B",
           "conditions": {"license_covers_venue": True,
                          "license_expires_at": "2027-12-31T23:59:59+08:00"}})
    b.add("LOAN_REQUESTED", "loan_request", "L-B-REP", t(25, "09:15"),
          "复制品总馆套改运北朝分馆",
          {"loan_id": "L-B-REP", "resource_id": "R-COSTUME-01",
           "resource_kind": "replica", "session_id": "S-2026-0927-B",
           "requested_by": "venue_beichao"})
    b.add("LOAN_APPROVED", "loan_request", "L-B-REP", t(25, "09:20"),
          "复制品改运批准",
          {"loan_id": "L-B-REP", "resource_id": "R-COSTUME-01",
           "session_id": "S-2026-0927-B",
           "conditions": {"vehicle_id": "VAN-05", "transport_fit": True}})
    b.add("RESOURCE_RESERVED", "collection_object", "O-TEX-07", t(25, "09:25"),
          "真品改预留至替代场", {"resource_id": "O-TEX-07", "session_id": "S-2026-0927-B"})
    b.add("RESOURCE_RESERVED", "replica", "R-COSTUME-01", t(25, "09:26"),
          "复制品总馆套改预留至替代场",
          {"resource_id": "R-COSTUME-01", "session_id": "S-2026-0927-B"})
    b.add("RESOURCE_RESERVED", "digital_content", "D-MEDIA-03", t(25, "09:27"),
          "互动程序授权改预留至替代场",
          {"resource_id": "D-MEDIA-03", "session_id": "S-2026-0927-B"})

    # 真品短驳：明堂 → 北朝
    b.add("TRANSFER_DISPATCHED", "transfer_order", "T-102", t(27, "08:30"),
          "真品由明堂短驳至北朝分馆",
          {"transfer_id": "T-102", "resource_ids": ["O-TEX-07"],
           "from_venue_id": "venue_mingtang", "to_venue_id": "venue_beichao",
           "planned_departure": t(27, "08:30"), "planned_arrival": t(27, "10:00"),
           "vehicle_id": "VAN-02", "session_id": "S-2026-0927-B"})
    b.add("TRANSFER_COMPLETED", "transfer_order", "T-102", t(27, "09:55"),
          "真品提前送达北朝分馆",
          {"transfer_id": "T-102", "resource_ids": ["O-TEX-07"],
           "arrived_at": t(27, "09:55")})
    b.add("TRANSFER_HANDOVER", "transfer_order", "T-102", t(27, "10:00"),
          "北朝分馆验收真品入恒湿柜",
          {"transfer_id": "T-102", "stage": "inbound_vault",
           "resource_ids": ["O-TEX-07"], "from_party": "押运组赵师傅",
           "to_party": "北朝分馆库房", "condition_check_passed": True,
           "at": t(27, "10:00")})
    b.add("ENVIRONMENT_READING_RECORDED", "venue", "venue_beichao", t(26, "20:00"),
          "北朝馆展前环境读数正常",
          {"venue_id": "venue_beichao", "observed_at": t(26, "20:00"),
           "temp_c": 20.1, "humidity_pct": 55.0, "breach": False})

    # ===== 9. 运力争用与迟延：VAN-05 被两单同时争用，复制品赶不上班次 =====
    b.add("TRANSFER_DISPATCHED", "transfer_order", "T-103", t(27, "07:30"),
          "同一辆车 VAN-05 另接城墙分馆展架运输单（争用暴露）",
          {"transfer_id": "T-103", "resource_ids": ["R-PANEL-88"],
           "from_venue_id": "venue_main", "to_venue_id": "venue_gucheng",
           "planned_departure": t(27, "07:30"), "planned_arrival": t(27, "13:30"),
           "vehicle_id": "VAN-05"})
    b.add("TRANSFER_DISPATCHED", "transfer_order", "T-104", t(27, "08:00"),
          "复制品总馆套装车发运北朝分馆（VAN-05）",
          {"transfer_id": "T-104", "resource_ids": ["R-COSTUME-01"],
           "from_venue_id": "venue_main", "to_venue_id": "venue_beichao",
           "planned_departure": t(27, "08:00"), "planned_arrival": t(27, "11:00"),
           "vehicle_id": "VAN-05", "session_id": "S-2026-0927-B"})
    delayed = b.add("TRANSFER_DELAYED", "transfer_order", "T-104", t(27, "11:30"),
                    "复制品运输迟延：先送城墙单导致绕行，预计15:00才到，赶不上14:00场次",
                    {"transfer_id": "T-104", "delay_minutes": 240,
                     "reason": "同车先执行城墙分馆展架单，路线冲突",
                     "new_eta": t(27, "15:00"),
                     "before_session_start": t(27, "14:00")})
    b.add("TRANSFER_CANCELLED", "transfer_order", "T-103", t(27, "11:35"),
          "调度取消城墙单的 VAN-05 安排，改派 VAN-07，解除争用",
          {"transfer_id": "T-103", "resource_ids": ["R-PANEL-88"],
           "reason": "为复制品教具让车"})

    # 只重排受影响资源：复制品改用北朝馆常备套；真品与数字内容不动
    b.add("SESSION_RESOURCES_REPLANNED", "activity_session", "S-2026-0927-B",
          t(27, "11:45"),
          "运输迟延只影响复制品：启用北朝馆常备套 R-COSTUME-02",
          {"session_id": "S-2026-0927-B", "trigger_event_id": delayed["event_id"],
           "released": ["R-COSTUME-01"],
           "reassigned": [{"resource_id": "R-COSTUME-02",
                           "resource_kind": "replica"}]})
    b.add("RESOURCE_RESERVED", "replica", "R-COSTUME-02", t(27, "11:46"),
          "北朝馆常备套紧急预留给替代场",
          {"resource_id": "R-COSTUME-02", "session_id": "S-2026-0927-B"})
    b.add("TRANSFER_COMPLETED", "transfer_order", "T-104", t(27, "15:05"),
          "复制品总馆套课后才抵达北朝分馆（本场未使用）",
          {"transfer_id": "T-104", "resource_ids": ["R-COSTUME-01"],
           "arrived_at": t(27, "15:05")})

    # ===== 10. 温湿度异常：只撤出真品，课程照常开 ===========================
    breach = b.add("ENVIRONMENT_READING_RECORDED", "venue", "venue_beichao",
                   t(27, "13:20"),
                   "北朝馆体验区空调故障，温湿度超标（场馆不停用，仅真品撤出）",
                   {"venue_id": "venue_beichao", "observed_at": t(27, "13:20"),
                    "temp_c": 24.6, "humidity_pct": 65.0, "breach": True})
    b.add("RESOURCE_RECALLED", "collection_object", "O-TEX-07", t(27, "13:25"),
          "真品按借调条件紧急召回撤出，复制品与数字内容不受影响",
          {"resource_id": "O-TEX-07", "reason": "展场温湿度超标，不符合纺织品条件"})
    b.add("SESSION_RESOURCES_REPLANNED", "activity_session", "S-2026-0927-B",
          t(27, "13:30"),
          "温湿度异常只撤出真品 O-TEX-07，其余资源不动，课程照常",
          {"session_id": "S-2026-0927-B",
           "trigger_event_id": breach["event_id"],
           "released": ["O-TEX-07"], "reassigned": []})

    # 真品当天押运回总馆
    b.add("TRANSFER_DISPATCHED", "transfer_order", "T-105", t(27, "16:30"),
          "真品提前撤回总馆",
          {"transfer_id": "T-105", "resource_ids": ["O-TEX-07"],
           "from_venue_id": "venue_beichao", "to_venue_id": "venue_main",
           "planned_departure": t(27, "16:30"), "planned_arrival": t(27, "18:00"),
           "vehicle_id": "VAN-02"})
    b.add("TRANSFER_COMPLETED", "transfer_order", "T-105", t(27, "17:50"),
          "真品运回总馆",
          {"transfer_id": "T-105", "resource_ids": ["O-TEX-07"],
           "arrived_at": t(27, "17:50")})
    b.add("RESOURCE_RETURNED", "collection_object", "O-TEX-07", t(27, "18:10"),
          "真品因环境异常提前归还，待检查",
          {"resource_id": "O-TEX-07", "return_kind": "early_recall",
           "from_session_id": "S-2026-0927-B"})
    b.add("RETURN_INSPECTED", "collection_object", "O-TEX-07", t(28, "10:00"),
          "真品回库检查通过，可再次使用",
          {"resource_id": "O-TEX-07", "result": "pass",
           "notes": "锦片纤维与色彩无异常，超标时间短且已封柜"})

    # ===== 11. 替代场实际交付与反馈 ========================================
    b.add("SESSION_DELIVERED", "activity_session", "S-2026-0927-B", t(27, "15:35"),
          "北魏服饰复原课在北朝艺术分馆实际交付（复制品+数字内容）",
          {"session_id": "S-2026-0927-B", "delivered_at": t(27, "15:35"),
           "actual_venue_id": "venue_beichao"})
    b.add("WAITLIST_EXPIRED", "waitlist_entry", "W-LI-02", t(27, "15:40"),
          "普通候补名额未出现，场后失效",
          {"waitlist_id": "W-LI-02", "reason": "场次已结束，普通池无释放"})
    b.add("FEEDBACK_SUBMITTED", "activity_feedback", "FB-01", t(27, "18:00"),
          "带队老师反馈：预约页地点、无障碍名额与现场一致",
          {"feedback_id": "FB-01", "session_id": "S-2026-0927-B",
           "author_role": "带队老师", "rating": 5,
           "comment": "闭馆换场当天就在预约页看到新地址和剩余无障碍名额；"
                      "真品因湿度撤出也有提示，孩子们用常备套完成了穿戴。"})
    b.add("FEEDBACK_SUBMITTED", "activity_feedback", "FB-02", t(27, "18:20"),
          "讲师反馈：定版材料与现场教具匹配",
          {"feedback_id": "FB-02", "session_id": "S-2026-0927-B",
           "author_role": "讲师", "rating": 4,
           "comment": "建议把环境异常时的数字替代讲解词写进下一版材料。"})

    # ===== 12. 北朝分馆离线：开始/完成补报（重复投递只认一次）==============
    started = b.add("OFFLINE_REPORT_STARTED", "activity_session",
                    "S-2026-0927-B", t(28, "09:00"),
                    "北朝馆网络恢复，补报昨日课后归档开始",
                    {"branch_id": "venue_beichao", "report_scope": "session_close",
                     "business_time": t(27, "15:50")},
                    dedupe_key="beichao-S-2026-0927-B-start",
                    branch_id="venue_beichao", source="offline_backfill")
    b.resend(started)  # 09:01 终端重试，dedupe_key 相同 → 必须被挡下
    completed = b.add("OFFLINE_REPORT_COMPLETED", "activity_session",
                      "S-2026-0927-B", t(28, "09:03"),
                      "北朝馆补报课后归档完成",
                      {"branch_id": "venue_beichao", "report_scope": "session_close",
                       "business_time": t(27, "16:10")},
                      dedupe_key="beichao-S-2026-0927-B-complete",
                      branch_id="venue_beichao", source="offline_backfill")
    b.resend(completed)

    # ===== 13. 讲解改版 v2：旧场次 B 仍锁定 v1 =============================
    b.add("INTERPRETATION_VERSION_PUBLISHED", "course_material", "interp-nw-v2",
          t(29, "10:00"),
          "讲解解释 v2 发布：垂裙幅冠改采“御寒保暖实用说”",
          {"version_id": "interp-nw-v2", "course_id": COURSE,
           "title": "北魏服饰讲解解释 v2",
           "excerpt": "据新出土平城墓群织物测算，垂裙主要用于颈部御寒，"
                      "风沙遮挡为次要功能；原“风帽说”不再作为主讲口径。"})
    b.add("MATERIAL_VERSION_PUBLISHED", "course_material", "material-nw-v2",
          t(29, "10:10"), "课程材料 v2 发布（增补环境异常数字替代讲解词）",
          {"version_id": "material-nw-v2", "course_id": COURSE,
           "title": "北魏服饰复原课材料包 v2",
           "excerpt": "新增：真品撤出时以互动程序三维放大观察的引导词。"})

    # ===== 14. 矿区场 C：复用迟延后转运的复制品；真品借调被拒；离线归还 ====
    b.add("SESSION_OPENED", "activity_session", "S-2026-1003-C", t(29, "11:00"),
          "矿区研学服务点场开放预约",
          {"session_id": "S-2026-1003-C", "course_id": COURSE,
           "title": "北魏服饰复原课·矿区场", "venue_id": "venue_kuangqu",
           "planned_start": "2026-10-03T10:00:00+08:00",
           "planned_end": "2026-10-03T11:30:00+08:00"})
    b.add("VENUE_CAPACITY_DEFINED", "venue_slot", "slot-C", t(29, "11:05"),
          "矿区场容量：普通15（无独立无障碍通道，不设无障碍池）",
          {"slot_id": "slot-C", "venue_id": "venue_kuangqu",
           "session_id": "S-2026-1003-C",
           "seats_by_pool": {"general": 15, "children_group": 0,
                             "mobility_access": 0}})
    b.add("SESSION_CONTENT_LOCKED", "activity_session", "S-2026-1003-C",
          t(29, "11:10"), "矿区场锁定新版 v2 讲解与材料",
          {"session_id": "S-2026-1003-C",
           "interpretation_version_id": "interp-nw-v2",
           "material_version_id": "material-nw-v2",
           "exhibit_version_id": "exhibit-nw-v1"})
    b.add("LOAN_REQUESTED", "loan_request", "L-C-REP", t(29, "11:20"),
          "申请复制品总馆套赴矿区场（课后已到北朝，再转运）",
          {"loan_id": "L-C-REP", "resource_id": "R-COSTUME-01",
           "resource_kind": "replica", "session_id": "S-2026-1003-C",
           "requested_by": "venue_kuangqu"})
    b.add("LOAN_APPROVED", "loan_request", "L-C-REP", t(29, "11:25"),
          "复制品借调批准",
          {"loan_id": "L-C-REP", "resource_id": "R-COSTUME-01",
           "session_id": "S-2026-1003-C",
           "conditions": {"vehicle_id": "VAN-06", "transport_fit": True}})
    b.add("LOAN_REQUESTED", "loan_request", "L-C-ORIG", t(29, "11:30"),
          "矿区场曾尝试申请真品",
          {"loan_id": "L-C-ORIG", "resource_id": "O-TEX-07",
           "resource_kind": "original", "session_id": "S-2026-1003-C",
           "requested_by": "venue_kuangqu"})
    b.add("LOAN_REJECTED", "loan_request", "L-C-ORIG", t(29, "11:35"),
          "真品借调拒绝：矿区点无恒温恒湿条件",
          {"loan_id": "L-C-ORIG", "resource_id": "O-TEX-07",
           "session_id": "S-2026-1003-C",
           "reasons": ["场地不具备纺织品温湿度展陈条件"]})
    b.add("RESOURCE_RESERVED", "replica", "R-COSTUME-01", t(29, "11:40"),
          "复制品总馆套预留给矿区场",
          {"resource_id": "R-COSTUME-01", "session_id": "S-2026-1003-C"})
    b.add("TRANSFER_DISPATCHED", "transfer_order", "T-106",
          "2026-10-01T09:00:00+08:00",
          "复制品由北朝分馆转运矿区服务点",
          {"transfer_id": "T-106", "resource_ids": ["R-COSTUME-01"],
           "from_venue_id": "venue_beichao", "to_venue_id": "venue_kuangqu",
           "planned_departure": "2026-10-01T09:00:00+08:00",
           "planned_arrival": "2026-10-01T11:00:00+08:00",
           "vehicle_id": "VAN-06", "session_id": "S-2026-1003-C"})
    b.add("TRANSFER_COMPLETED", "transfer_order", "T-106", "2026-10-01T10:50:00+08:00",
          "复制品送达矿区服务点",
          {"transfer_id": "T-106", "resource_ids": ["R-COSTUME-01"],
           "arrived_at": "2026-10-01T10:50:00+08:00"})
    b.add("INSTRUCTOR_ASSIGNED", "instructor", "I-LIN-01", "2026-10-01T12:00:00+08:00",
          "林砚承担矿区场",
          {"instructor_id": "I-LIN-01", "session_id": "S-2026-1003-C",
           "qualification_version": "qual-2026.03"})
    b.add("SESSION_DELIVERED", "activity_session", "S-2026-1003-C",
          "2026-10-03T11:35:00+08:00",
          "矿区场实际交付",
          {"session_id": "S-2026-1003-C", "delivered_at": "2026-10-03T11:35:00+08:00",
           "actual_venue_id": "venue_kuangqu"})

    # 矿区点课后断网，次日恢复后补报归还（只认一次）
    ret = b.add("OFFLINE_RETURN_REPORTED", "activity_session", "S-2026-1003-C",
                "2026-10-04T08:30:00+08:00",
                "矿区点恢复网络，补报复制品已在 10/3 课后点收待退",
                {"branch_id": "venue_kuangqu", "resource_ids": ["R-COSTUME-01"],
                 "session_id": "S-2026-1003-C",
                 "business_time": "2026-10-03T16:00:00+08:00"},
                dedupe_key="kuangqu-S-2026-1003-C-return",
                branch_id="venue_kuangqu", source="offline_backfill")
    b.resend(ret)  # 矿区终端重试，同一补报不得第二次入账

    # 实物随后运回总馆、检查通过、可再次使用
    b.add("TRANSFER_DISPATCHED", "transfer_order", "T-107",
          "2026-10-04T09:00:00+08:00",
          "复制品由矿区运回总馆",
          {"transfer_id": "T-107", "resource_ids": ["R-COSTUME-01"],
           "from_venue_id": "venue_kuangqu", "to_venue_id": "venue_main",
           "planned_departure": "2026-10-04T09:00:00+08:00",
           "planned_arrival": "2026-10-04T11:00:00+08:00",
           "vehicle_id": "VAN-06"})
    b.add("TRANSFER_COMPLETED", "transfer_order", "T-107",
          "2026-10-04T10:55:00+08:00",
          "复制品运回总馆",
          {"transfer_id": "T-107", "resource_ids": ["R-COSTUME-01"],
           "arrived_at": "2026-10-04T10:55:00+08:00"})
    b.add("RETURN_INSPECTED", "replica", "R-COSTUME-01",
          "2026-10-05T09:30:00+08:00",
          "复制品归还检查通过，可再次使用",
          {"resource_id": "R-COSTUME-01", "result": "pass",
           "notes": "幅冠系带磨损在允许范围，已登记例行维保"})

    return b.events


def main() -> None:
    events = build()
    target = ROOT / "data" / "scenario_northern_wei.json"
    target.write_text(json.dumps(events, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(f"已生成 {target.relative_to(ROOT)}，共 {len(events)} 条事件")


if __name__ == "__main__":
    main()
