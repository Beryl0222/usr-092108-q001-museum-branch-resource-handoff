"""业务策略：借调条件、异常影响范围、保障容量、讲师与运力争用。

全部为纯函数，输入是重放投影出的普通字典，便于单独测试。
"""

from datetime import datetime, timedelta
from typing import Iterable

from .catalog import PROTECTED_POOLS

# 纺织品（北魏服饰）真品借出门的温湿度区间。
ORIGINAL_TEMP_RANGE = (15.0, 22.0)
ORIGINAL_HUMIDITY_RANGE = (50.0, 60.0)

# 讲师在不同分馆连场之间的最小路途缓冲。
DEFAULT_TRAVEL_GAP = timedelta(minutes=45)


class Decision:
    """审批/分配结论。approved 为 False 时 reasons 给出全部命中的原因。"""

    def __init__(self, approved: bool, reasons: list[str] | None = None):
        self.approved = approved
        self.reasons = reasons or []

    def __bool__(self) -> bool:
        return self.approved

    def __repr__(self) -> str:
        return f"Decision(approved={self.approved}, reasons={self.reasons!r})"


# --- 三类资源各自的借调条件 ---------------------------------------------------

def evaluate_loan(resource: dict, venue: dict, session: dict, plan: dict) -> Decision:
    """按资源种类走不同审批条件。

    resource：resource_kind/title/status/holds/license 等台账字段；
    venue：场地状态与环境能力（replay.venue_view）；
    session：场次时间窗；
    plan：本次借调的随附条件（保险、押运、车辆、授权等）。
    """
    kind = resource["resource_kind"]
    if kind == "original":
        return _evaluate_original_loan(resource, venue, session, plan)
    if kind == "replica":
        return _evaluate_replica_loan(resource, venue, session, plan)
    if kind == "digital":
        return _evaluate_digital_loan(resource, venue, session, plan)
    return Decision(False, [f"未知资源种类：{kind}"])


def _evaluate_original_loan(resource: dict, venue: dict, session: dict, plan: dict) -> Decision:
    reasons: list[str] = []
    # 1. 场地环境能力：纺织品温湿度标准，且现场无未消除的环境超标。
    if not venue.get("env_capable_for_textile"):
        reasons.append("场地不具备纺织品温湿度展陈条件")
    if venue.get("latest_breach"):
        reasons.append("场地最近一次环境读数超标，真品不得调入")
    # 2. 台账状态：无未处理病害/保留意见，未被冻结。
    if resource.get("status") == "blocked":
        reasons.append("真品已被冻结（存在未处理病害或保留意见）")
    if resource.get("holds"):
        reasons.append("真品存在未消除的保留意见：" + "、".join(resource["holds"]))
    # 3. 保险与押运随借同行，缺一不批。
    if not plan.get("insurance_confirmed"):
        reasons.append("缺少借展保险确认")
    if not plan.get("escort_confirmed"):
        reasons.append("缺少押运人员确认")
    # 4. 场馆停用窗口与场次时间冲突。
    if venue.get("status") == "out_of_service":
        reasons.append("场地处于停用状态")
    return Decision(not reasons, reasons)


def _evaluate_replica_loan(resource: dict, venue: dict, session: dict, plan: dict) -> Decision:
    reasons: list[str] = []
    if resource.get("status") == "blocked":
        reasons.append("复制品正在检修，不可外借")
    # 复制品只看可运输性：尺寸重量与车辆装载匹配。
    if not plan.get("transport_fit"):
        reasons.append("车辆装载能力不足（尺寸或重量超限）")
    if not plan.get("vehicle_id"):
        reasons.append("未安排运输车辆")
    if venue.get("status") == "out_of_service":
        reasons.append("场地处于停用状态")
    return Decision(not reasons, reasons)


def _evaluate_digital_loan(resource: dict, venue: dict, session: dict, plan: dict) -> Decision:
    reasons: list[str] = []
    if resource.get("status") == "blocked":
        reasons.append("数字内容已停用（如授权撤回）")
    # 数字内容只看授权范围：授权场馆、授权场次时间与到期日。
    if not plan.get("license_covers_venue"):
        reasons.append("授权范围不覆盖该分馆")
    expiry = plan.get("license_expires_at")
    end = session.get("planned_end")
    if expiry and end and _parse(expiry) < _parse(end):
        reasons.append("授权在场次结束前到期")
    if not venue.get("playback_ready"):
        reasons.append("场地缺少可播放设备")
    return Decision(not reasons, reasons)


def environment_allows(reading: dict) -> bool:
    """环境读数是否满足纺织品真品条件。"""
    t, h = reading.get("temp_c"), reading.get("humidity_pct")
    if t is None or h is None:
        return False
    return (ORIGINAL_TEMP_RANGE[0] <= t <= ORIGINAL_TEMP_RANGE[1]
            and ORIGINAL_HUMIDITY_RANGE[0] <= h <= ORIGINAL_HUMIDITY_RANGE[1])


# --- 异常影响范围：只重排受影响资源 ------------------------------------------

def impacted_resources(trigger: str, payload: dict, resources: dict,
                       sessions: dict, transfers: dict) -> dict[str, str]:
    """返回 {resource_id: 受影响原因}；不在范围内的资源一律不动。

    - transfer_delay（运输迟延）：只有该运输单上、且赶不上班次开始的资源；
    - environment_breach（温湿度异常）：只召回该场地内的真品，复制品与数字内容照常；
    - venue_out_of_service（场馆停用）：停用窗口内该场馆场次锁定的资源。
    """
    impacted: dict[str, str] = {}
    if trigger == "transfer_delay":
        order = transfers.get(payload["transfer_id"], {})
        deadline = _parse(payload["before_session_start"])
        new_arrival = _parse(payload["new_eta"])
        if new_arrival > deadline:
            for rid in order.get("resource_ids", []):
                impacted[rid] = f"运输单 {payload['transfer_id']} 迟延，赶不上班次"
        return impacted

    if trigger == "environment_breach":
        venue_id = payload["venue_id"]
        for rid, res in resources.items():
            if (res.get("resource_kind") == "original"
                    and res.get("location_venue_id") == venue_id):
                impacted[rid] = f"场馆 {venue_id} 温湿度异常，真品按条件必须撤出"
        # 复制品、数字内容不依赖恒温恒湿，不在影响范围内。
        return impacted

    if trigger == "venue_out_of_service":
        venue_id = payload["venue_id"]
        window_start = _parse(payload["from_time"])
        window_end = _parse(payload["to_time"])
        for sid, sess in sessions.items():
            if sess.get("venue_id") != venue_id:
                continue
            if _windows_overlap(window_start, window_end,
                                _parse(sess["planned_start"]), _parse(sess["planned_end"])):
                # 投影中场次资源是 dict（resource_id -> kind），兼容裸列表输入。
                resources = sess.get("resource_history") or sess.get("resources") or {}
                rids = resources.keys() if isinstance(resources, dict) else resources
                for rid in rids:
                    impacted[rid] = f"场馆 {venue_id} 停用，场次 {sid} 需改址"
        return impacted

    raise ValueError(f"未知异常触发来源：{trigger}")


def _windows_overlap(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


# --- 保障容量：儿童团体与行动不便者名额独立记账 -------------------------------

def try_allocate(slot: dict, seats_by_pool: dict,
                 entitlement: Iterable[str] = ()) -> Decision:
    """容量分配尝试。

    - 普通预约只能使用 general 池，禁止占用 children_group / mobility_access；
    - 持相应资格（儿童团体、行动不便）才能使用对应保障池；
    - 保障池不足时可回落普通池，但保障池余额绝不被普通预约平分。
    """
    entitlement = set(entitlement)
    requested = {p: int(n) for p, n in seats_by_pool.items() if n}
    reasons: list[str] = []

    # 保障池必须凭资格使用；普通预约永远不能占用保障名额。
    for pool in PROTECTED_POOLS:
        if requested.get(pool, 0) > 0 and pool not in entitlement:
            reasons.append(f"无权占用保障池 {pool}（需相应资格）")
    if requested.get("general", 0) > _remaining(slot, "general"):
        reasons.append(f"普通池余额不足（剩余 {_remaining(slot, 'general')}），"
                       "不得占用儿童/无障碍保障名额")
    for pool in PROTECTED_POOLS:
        if requested.get(pool, 0) > _remaining(slot, pool):
            reasons.append(f"保障池 {pool} 余额不足（剩余 {_remaining(slot, pool)}）")

    # 保障需求超出保障池时，可在预约阶段显式回落普通池（在 seats_by_pool 中
    # 另列 general 名额）；这里不自动把保障名额挪给普通预约。
    return Decision(not reasons, reasons)


def _remaining(slot: dict, pool: str) -> int:
    return int(slot["seats_by_pool"].get(pool, 0)) - int(slot["assigned_by_pool"].get(pool, 0))


def promote_waitlist(slot: dict, entries: list[dict], pool: str,
                     seats: int) -> list[str]:
    """某池释放名额后按 FIFO 补位，只晋升与该池匹配的候补条目。

    返回被晋升的 waitlist_id；其余候补继续等待，保障池名额不挪作普通用途。
    """
    promoted: list[str] = []
    for entry in sorted(entries, key=lambda e: e["created_seq"]):
        if seats <= 0:
            break
        if entry.get("status") != "waiting":
            continue
        if entry["pool"] != pool:
            continue
        take = min(seats, int(entry["seats"]))
        if take <= _remaining(slot, pool):
            promoted.append(entry["waitlist_id"])
            seats -= take
    return promoted


# --- 讲师与运力争用检测 -------------------------------------------------------

def find_instructor_conflicts(assignments: list[dict],
                              travel_gap: timedelta = DEFAULT_TRAVEL_GAP) -> list[dict]:
    """同一讲师重叠排课，或跨馆连场路途缓冲不足。"""
    conflicts: list[dict] = []
    by_instructor: dict[str, list[dict]] = {}
    for item in assignments:
        by_instructor.setdefault(item["instructor_id"], []).append(item)
    for instructor_id, items in by_instructor.items():
        items = sorted(items, key=lambda i: _parse(i["planned_start"]))
        for prev, nxt in zip(items, items[1:]):
            gap = _parse(nxt["planned_start"]) - _parse(prev["planned_end"])
            if gap < timedelta(0):
                conflicts.append({
                    "type": "overlap",
                    "instructor_id": instructor_id,
                    "sessions": [prev["session_id"], nxt["session_id"]],
                })
            elif prev["venue_id"] != nxt["venue_id"] and gap < travel_gap:
                conflicts.append({
                    "type": "travel_gap_too_short",
                    "instructor_id": instructor_id,
                    "sessions": [prev["session_id"], nxt["session_id"]],
                    "gap_minutes": int(gap.total_seconds() // 60),
                })
    return conflicts


def find_vehicle_conflicts(transfers: list[dict]) -> list[dict]:
    """同一运输车辆的时间窗重叠（同一批运输能力被多馆争用）。"""
    conflicts: list[dict] = []
    by_vehicle: dict[str, list[dict]] = {}
    for order in transfers:
        if order.get("vehicle_id"):
            by_vehicle.setdefault(order["vehicle_id"], []).append(order)
    for vehicle_id, orders in by_vehicle.items():
        orders = sorted(orders, key=lambda o: _parse(o["planned_departure"]))
        for prev, nxt in zip(orders, orders[1:]):
            if _parse(nxt["planned_departure"]) < _parse(prev["planned_arrival"]):
                conflicts.append({
                    "type": "vehicle_double_booked",
                    "vehicle_id": vehicle_id,
                    "transfers": [prev["transfer_id"], nxt["transfer_id"]],
                })
    return conflicts


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)
