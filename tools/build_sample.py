"""生成 data/sample.json：北魏服饰复原课跨馆资源接力完整事件流。

运行：python3 tools/build_sample.py
事件按实际发生时间顺序写出；event_id 与各聚合内 version 由本脚本自动编号，
避免手工维护序号。故事线见 docs/domain-model.md。
"""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "sample.json"
CORR = "RELAY-20261017-BEIWEI"

_agg_versions: dict[str, int] = {}
_seq = 0
_events: list[dict] = []


def E(event_type, agg_type, agg_id, at, summary, *, key=None, cause=None, corr=False, **payload):
    """按时间顺序追加一条事件；返回引用记号，排序编号后回填为真实 event_id。"""
    global _seq
    _seq += 1
    ver = _agg_versions.get(agg_id, 0) + 1
    _agg_versions[agg_id] = ver
    event = {
        "_ref": f"ref-{_seq}",
        "event_id": None,
        "event_type": event_type,
        "aggregate_type": agg_type,
        "aggregate_id": agg_id,
        "occurred_at": at if "+" in at else f"{at}+08:00",
        "version": ver,
        "summary": summary,
    }
    if key:
        event["idempotency_key"] = key
    if cause:
        event["_cause_ref"] = cause
    if corr:
        event["correlation_id"] = CORR
    if payload:
        event["payload"] = payload
    _events.append(event)
    return event["_ref"]


# ── 一、在册身份：总馆与九座分馆 ──────────────────────────────────────────
branches = [
    ("V-MAIN", "大同市博物馆总馆", 120, True),
    ("V-MT", "北魏明堂分馆", 30, True),
    ("V-PC", "平城遗址分馆", 30, True),
    ("V-YG", "云冈石窟分馆", 60, True),
    ("V-HH", "北朝艺术分馆", 40, True),
    ("V-SJ", "史前大同分馆", 35, False),
    ("V-MR", "明代边关分馆", 25, False),
    ("V-CH", "长城抗战分馆", 45, True),
    ("V-MZ", "民族融合分馆", 30, True),
    ("V-WH", "魏碑书法分馆", 20, False),
]
for i, (vid, name, cap, acc) in enumerate(branches, start=1):
    E("VENUE_REGISTERED", "venue", vid, f"2026-01-{i:02d}T09:00:00",
      f"登记{name}", venue_id=vid, branch_name=name, default_capacity=cap,
      step_free_access=acc, storage_available=True)

# ── 二、在册身份：真品 / 复制品 / 数字内容 ────────────────────────────────
E("RESOURCE_REGISTERED", "collection_resource", "R-AUTH-01", "2026-02-02T10:00:00",
  "登记馆藏真品：北魏彩绘陶俑（鲜卑常服）", resource_kind="authentic_object",
  name="北魏彩绘陶俑", home_venue_id="V-MAIN",
  environment_requirements={"temperature_c": [18, 22], "humidity_pct": [45, 60]})
E("RESOURCE_REGISTERED", "movable_replica", "R-REP-01", "2026-02-03T10:00:00",
  "登记复制教具：北魏鲜卑常服一套（主用）", resource_kind="replica",
  name="鲜卑常服复制教具（主用）", home_venue_id="V-MAIN")
E("RESOURCE_REGISTERED", "movable_replica", "R-REP-02", "2026-02-03T10:05:00",
  "登记复制教具：北魏鲜卑常服一套（备用）", resource_kind="replica",
  name="鲜卑常服复制教具（备用）", home_venue_id="V-MAIN")
E("RESOURCE_REGISTERED", "movable_replica", "R-REP-03", "2026-02-04T10:00:00",
  "登记复制教具：彩绘陶俑等比例复制件", resource_kind="replica",
  name="彩绘陶俑复制件", home_venue_id="V-MAIN")
E("RESOURCE_REGISTERED", "digital_content", "D-DIG-01", "2026-02-05T10:00:00",
  "登记数字内容：北魏服饰复原数字走秀（可并发授权，不占运力）",
  resource_kind="digital", name="北魏服饰数字走秀", home_venue_id="V-MAIN",
  concurrent_licenses=9)

# ── 三、在册身份：展陈版本、讲解版本、课程材料、讲师 ──────────────────────
E("EXHIBIT_VERSION_PUBLISHED", "exhibit_version", "EX-BEIWEI-V1", "2026-08-10T09:00:00",
  "发布《北魏服饰》展陈版本 v1", exhibit_id="EX-BEIWEI", version_tag="v1",
  title="北魏服饰展陈（初版）")
E("INTERPRETATION_PUBLISHED", "interpretation", "INT-BEIWEI-V1", "2026-08-10T09:30:00",
  "发布讲解口径 v1（平城鲜卑服制初考）", interpretation_id="INT-BEIWEI",
  version_tag="v1", title="平城鲜卑服制初考")
E("COURSE_MATERIAL_PUBLISHED", "course_material", "CM-BEIWEI-RESTORE", "2026-08-12T09:00:00",
  "发布课程《北魏服饰复原课》材料 v1", course_code="CM-BEIWEI-RESTORE",
  version_tag="v1", title="北魏服饰复原课", materials=["讲义v1", "穿戴耗材清单v1"])
E("EDUCATOR_REGISTERED", "educator", "EDU-SHEN", "2026-08-03T09:00:00",
  "登记讲师沈老师（北魏服饰方向，可授复原课）", educator_id="EDU-SHEN",
  name="沈老师", qualified_courses=["CM-BEIWEI-RESTORE"],
  qualification_valid_until="2027-08-02")
E("EDUCATOR_REGISTERED", "educator", "EDU-HE", "2026-08-03T09:05:00",
  "登记讲师何老师（史前陶器方向，不可授复原课）", educator_id="EDU-HE",
  name="何老师", qualified_courses=["CM-PREHISTORIC-POTTERY"],
  qualification_valid_until="2027-08-02")

# ── 四、10/17 明堂分馆场次开仓与保障名额 ─────────────────────────────────
E("SESSION_OPENED", "program_session", "S-20261017-MT", "2026-09-22T09:00:00",
  "10月17日北魏服饰复原课在北魏明堂分馆开仓预约", corr=True,
  session_id="S-20261017-MT", venue_id="V-MT", course_code="CM-BEIWEI-RESTORE",
  scheduled_start="2026-10-17T10:00:00+08:00", scheduled_end="2026-10-17T11:30:00+08:00",
  capacity=26, protected_children_seats=12, accessible_seats=4)
E("SESSION_QUOTA_PROTECTED", "program_session", "S-20261017-MT", "2026-09-22T09:05:00",
  "登记保障名额：儿童团体12席、无障碍4席，保留至开场前48小时", corr=True,
  protected_children_seats=12, accessible_seats=4, protect_until="2026-10-15T10:00:00+08:00")
E("SESSION_CONTENT_PINNED", "program_session", "S-20261017-MT", "2026-09-22T09:10:00",
  "本场固化讲解v1、展陈v1、材料v1", corr=True,
  interpretation_id="INT-BEIWEI", interpretation_version="v1",
  exhibit_id="EX-BEIWEI", exhibit_version="v1",
  course_material_version="v1")
E("EDUCATOR_ASSIGNED", "program_session", "S-20261017-MT", "2026-09-22T09:15:00",
  "指派沈老师授课（资质在有效期内、课程匹配）", corr=True,
  educator_id="EDU-SHEN", educator_aggregate="EDU-SHEN")

# ── 五、资源预约：真品 + 复制品 + 数字内容 ───────────────────────────────
E("RESOURCE_RESERVED", "collection_resource", "R-AUTH-01", "2026-09-22T09:20:00",
  "真品陶俑预约给明堂场次（须环境达标）", corr=True,
  resource_kind="authentic_object", session_id="S-20261017-MT", venue_id="V-MT")
E("RESOURCE_RESERVED", "movable_replica", "R-REP-01", "2026-09-22T09:25:00",
  "主用复制教具预约给明堂场次", corr=True,
  resource_kind="replica", session_id="S-20261017-MT", venue_id="V-MT")
E("RESOURCE_RESERVED", "digital_content", "D-DIG-01", "2026-09-22T09:30:00",
  "数字走秀授权明堂场次并发使用", corr=True,
  resource_kind="digital", session_id="S-20261017-MT", venue_id="V-MT")

# ── 六、团体预约与散客候补 ───────────────────────────────────────────────
E("GROUP_BOOKING_CREATED", "group_booking", "B-2026-001", "2026-09-23T10:00:00",
  "城区三小三年级团体报名12人（儿童团体）", corr=True,
  session_id="S-20261017-MT", group_name="城区三小三年级", seats=12,
  quota_class="children", contact_role="带队老师")
E("BOOKING_CONFIRMED", "group_booking", "B-2026-001", "2026-09-23T10:05:00",
  "儿童团体12席确认，占用儿童保障名额12/12", corr=True,
  session_id="S-20261017-MT", seats=12, quota_class="children")
E("GROUP_BOOKING_CREATED", "group_booking", "B-2026-002", "2026-09-24T10:00:00",
  "阳光之家行动不便者家庭报名4人（含4辆轮椅）", corr=True,
  session_id="S-20261017-MT", group_name="阳光之家家庭", seats=4,
  quota_class="accessible", contact_role="家属代表")
E("BOOKING_CONFIRMED", "group_booking", "B-2026-002", "2026-09-24T10:05:00",
  "无障碍席位4席确认 4/4", corr=True,
  session_id="S-20261017-MT", seats=4, quota_class="accessible")
E("GROUP_BOOKING_CREATED", "group_booking", "B-2026-003", "2026-09-25T10:00:00",
  "普通研学团报名10人", corr=True,
  session_id="S-20261017-MT", group_name="朔北研学团", seats=10,
  quota_class="general", contact_role="随团导师")
E("BOOKING_CONFIRMED", "group_booking", "B-2026-003", "2026-09-25T10:05:00",
  "普通席10席确认 10/10，本场约满", corr=True,
  session_id="S-20261017-MT", seats=10, quota_class="general")
E("WAITLIST_ENTRY_ADDED", "waitlist_entry", "W-001", "2026-09-26T09:00:00",
  "散客王女士（轮椅使用者）登记无障碍候补，顺位1", corr=True,
  session_id="S-20261017-MT", party_label="王女士一行", party_size=1,
  requested_class="accessible", position=1)
E("WAITLIST_ENTRY_ADDED", "waitlist_entry", "W-002", "2026-09-26T09:30:00",
  "散客高先生父女登记普通候补，顺位2", corr=True,
  session_id="S-20261017-MT", party_label="高先生父女", party_size=2,
  requested_class="general", position=2)
E("WAITLIST_ENTRY_ADDED", "waitlist_entry", "W-003", "2026-09-26T10:00:00",
  "散客赵同学登记普通候补，顺位3", corr=True,
  session_id="S-20261017-MT", party_label="赵同学", party_size=1,
  requested_class="general", position=3)

# ── 七、10/15 温湿度异常：只撤回真品，复制品/数字内容不动 ────────────────
E("CONDITION_RECORDED", "venue", "V-MT", "2026-10-15T13:50:00",
  "明堂分馆库环境读数：湿度68%，逼近上限", corr=True,
  venue_id="V-MT", reading={"temperature_c": 21.0, "humidity_pct": 68})
id_alert = E("ENVIRONMENT_ALERT_RAISED", "venue", "V-MT", "2026-10-15T14:00:00",
  "明堂分馆湿度升至72%，超出真品借调条件（45%-60%）", corr=True,
  venue_id="V-MT", reading={"temperature_c": 21.2, "humidity_pct": 72},
  violated_requirement="humidity_pct")
E("RESOURCE_RESERVATION_RELEASED", "collection_resource", "R-AUTH-01", "2026-10-15T14:10:00",
  "真品陶俑预约撤回、暂不出库（复制品与数字内容预约保留）", corr=True,
  cause=id_alert,
  resource_kind="authentic_object", session_id="S-20261017-MT",
  reason="environment_alert")
E("RESOURCE_QUARANTINED", "collection_resource", "R-AUTH-01", "2026-10-15T14:15:00",
  "真品暂缓借调，待场馆环境恢复并复检", corr=True,
  cause=id_alert, resource_kind="authentic_object", reason="environment_alert")
E("RESOURCE_RESERVED", "movable_replica", "R-REP-03", "2026-10-15T14:30:00",
  "启用陶俑复制件顶替真品（同场复制品，仅受影响资源被替换）", corr=True,
  cause=id_alert, resource_kind="replica",
  session_id="S-20261017-MT", venue_id="V-MT", replaces_resource="R-AUTH-01")

# ── 八、运输计划 T-01；普通团体取消，候补按顺位晋升/过期 ─────────────────
E("TRANSFER_PLANNED", "transfer_order", "T-2026-001", "2026-10-15T16:00:00",
  "排运 T-01：主用教具与陶俑复制件 总馆→明堂分馆", corr=True,
  transfer_order_id="T-2026-001", resources=["R-REP-01", "R-REP-03"],
  from_venue_id="V-MAIN", to_venue_id="V-MT",
  planned_arrival="2026-10-16T10:30:00+08:00")
E("BOOKING_CANCELLED", "group_booking", "B-2026-003", "2026-10-15T17:00:00",
  "普通研学团因行程冲突取消10席，普通席腾空", corr=True,
  session_id="S-20261017-MT", seats=10, quota_class="general")
E("WAITLIST_ENTRY_PROMOTED", "waitlist_entry", "W-002", "2026-10-15T17:05:00",
  "候补顺位2高先生父女晋升并获2席", corr=True,
  session_id="S-20261017-MT", party_size=2, requested_class="general")
E("GROUP_BOOKING_CREATED", "group_booking", "B-2026-004", "2026-10-15T17:08:00",
  "高先生父女候补转正，生成预约单", corr=True,
  session_id="S-20261017-MT", group_name="高先生家庭", seats=2,
  quota_class="general", from_waitlist="W-002")
E("BOOKING_CONFIRMED", "group_booking", "B-2026-004", "2026-10-15T17:10:00",
  "高先生家庭2席确认（普通席 2/10）", corr=True,
  session_id="S-20261017-MT", seats=2, quota_class="general")
E("WAITLIST_ENTRY_PROMOTED", "waitlist_entry", "W-003", "2026-10-15T17:12:00",
  "候补顺位3赵同学获晋升机会（普通席余8）", corr=True,
  session_id="S-20261017-MT", party_size=1, requested_class="general",
  offer_expires_at="2026-10-15T20:12:00+08:00")
E("WAITLIST_ENTRY_EXPIRED", "waitlist_entry", "W-003", "2026-10-15T20:15:00",
  "赵同学3小时内未确认，晋升名额作废，候补条目失效", corr=True,
  session_id="S-20261017-MT", reason="offer_not_confirmed")

# ── 九、10/16 T-01 迟延：只调备用教具急送 T-02 ───────────────────────────
E("TRANSFER_DISPATCHED", "transfer_order", "T-2026-001", "2026-10-16T08:00:00",
  "T-01 发货（厢式货车，同车另有他馆物资，不拆拼他单）", corr=True,
  resources=["R-REP-01", "R-REP-03"], from_venue_id="V-MAIN", to_venue_id="V-MT",
  carrier_capacity="van-1")
id_delay = E("TRANSFER_DELAYED", "transfer_order", "T-2026-001", "2026-10-16T11:00:00",
  "T-01 因道路封闭预计15:30才到，晚于课前查验窗口", corr=True,
  resources=["R-REP-01", "R-REP-03"], reason="road_closure",
  revised_eta="2026-10-16T15:30:00+08:00")
E("RESOURCE_RESERVED", "movable_replica", "R-REP-02", "2026-10-16T11:10:00",
  "紧急启用备用复制教具顶替（仅重排迟延运单上的资源）", corr=True,
  cause=id_delay, resource_kind="replica",
  session_id="S-20261017-MT", venue_id="V-MT")
E("TRANSFER_PLANNED", "transfer_order", "T-2026-002", "2026-10-16T11:20:00",
  "排急运 T-02：备用教具 总馆→明堂分馆", corr=True,
  transfer_order_id="T-2026-002", resources=["R-REP-02"],
  from_venue_id="V-MAIN", to_venue_id="V-MT",
  planned_arrival="2026-10-16T12:40:00+08:00")
E("TRANSFER_DISPATCHED", "transfer_order", "T-2026-002", "2026-10-16T11:30:00",
  "T-02 发货（应急小车）", corr=True,
  resources=["R-REP-02"], from_venue_id="V-MAIN", to_venue_id="V-MT")
E("TRANSFER_HANDED_OVER", "transfer_order", "T-2026-002", "2026-10-16T12:40:00",
  "T-02 到达明堂分馆，馆员与司机当面交接", corr=True,
  resources=["R-REP-02"], handed_over_at="V-MT",
  receiver_role="明堂分馆库管员")
E("TRANSFER_ACKNOWLEDGED", "transfer_order", "T-2026-002", "2026-10-16T12:50:00",
  "T-02 签收：备用教具外包装完好", corr=True,
  resources=["R-REP-02"], acknowledged_at="V-MT",
  inspector_role="明堂分馆库管员")
E("CONDITION_RECORDED", "movable_replica", "R-REP-02", "2026-10-16T12:55:00",
  "备用教具到场查验：服饰配件齐全、无污损", corr=True,
  resource_kind="replica", condition_result="合格", inspected_at="V-MT")
E("RESOURCE_CLEARED", "movable_replica", "R-REP-02", "2026-10-16T13:00:00",
  "备用教具查验合格、可用于本场", corr=True,
  resource_kind="replica", inspected_at="V-MT")
E("TRANSFER_CLOSED", "transfer_order", "T-2026-002", "2026-10-16T13:10:00",
  "T-02 运单关闭", corr=True, resources=["R-REP-02"])
E("TRANSFER_HANDED_OVER", "transfer_order", "T-2026-001", "2026-10-16T15:30:00",
  "T-01 迟延抵达明堂分馆并交接", corr=True,
  resources=["R-REP-01", "R-REP-03"], handed_over_at="V-MT",
  receiver_role="明堂分馆库管员")
E("TRANSFER_ACKNOWLEDGED", "transfer_order", "T-2026-001", "2026-10-16T15:40:00",
  "T-01 签收：两件教具外观完好，待课前复检", corr=True,
  resources=["R-REP-01", "R-REP-03"], acknowledged_at="V-MT")
E("TRANSFER_CLOSED", "transfer_order", "T-2026-001", "2026-10-16T15:50:00",
  "T-01 运单关闭（迟延已记录）", corr=True,
  resources=["R-REP-01", "R-REP-03"])

# ── 十、10/16 晚临时闭馆：整体迁移平城遗址分馆，名额平移 ─────────────────
id_out = E("VENUE_TAKEN_OUT_OF_SERVICE", "venue", "V-MT", "2026-10-16T18:00:00",
  "明堂分馆供暖管道故障，10月17日临时闭馆", corr=True,
  venue_id="V-MT", reason="heating_pipe_failure",
  closed_dates=["2026-10-17"])
id_reloc = E("SESSION_RELOCATED", "program_session", "S-20261017-MT", "2026-10-16T18:20:00",
  "本场整体迁移至平城遗址分馆替代场次，同档期同时间", corr=True,
  cause=id_out, venue_id="V-MT", to_venue_id="V-PC",
  replacement_session_id="S-20261017-PC")
E("SESSION_OPENED", "program_session", "S-20261017-PC", "2026-10-16T18:25:00",
  "替代场次在平城遗址分馆开仓（无障碍席位6，不少于原场4）", corr=True,
  cause=id_reloc, session_id="S-20261017-PC", venue_id="V-PC",
  course_code="CM-BEIWEI-RESTORE",
  scheduled_start="2026-10-17T10:00:00+08:00", scheduled_end="2026-10-17T11:30:00+08:00",
  capacity=30, protected_children_seats=12, accessible_seats=6,
  original_session_id="S-20261017-MT",
  transferred_bookings=["B-2026-001", "B-2026-002", "B-2026-004"])
E("SESSION_QUOTA_PROTECTED", "program_session", "S-20261017-PC", "2026-10-16T18:26:00",
  "替代场次保障名额登记：儿童12、无障碍6（原名额平移，不重抽）", corr=True,
  cause=id_reloc, protected_children_seats=12, accessible_seats=6,
  transferred_from="S-20261017-MT")
E("SESSION_CONTENT_PINNED", "program_session", "S-20261017-PC", "2026-10-16T18:27:00",
  "替代场次沿用固化的讲解v1、展陈v1、材料v1", corr=True,
  cause=id_reloc, interpretation_id="INT-BEIWEI", interpretation_version="v1",
  exhibit_id="EX-BEIWEI", exhibit_version="v1", course_material_version="v1")
for bid, name, seats, qclass, confirmed_at in [
    ("B-2026-001", "城区三小三年级", 12, "children", "2026-09-23T10:05:00+08:00"),
    ("B-2026-002", "阳光之家家庭", 4, "accessible", "2026-09-24T10:05:00+08:00"),
    ("B-2026-004", "高先生家庭", 2, "general", "2026-10-15T17:10:00+08:00"),
]:
    E("BOOKING_CONFIRMED", "group_booking", bid, "2026-10-16T18:30:00",
      f"{name}预约平移至替代场次并重新确认，保留原确认时间", corr=True,
      cause=id_reloc, session_id="S-20261017-PC", seats=seats,
      quota_class=qclass, original_session_id="S-20261017-MT",
      original_confirmed_at=confirmed_at)
E("EDUCATOR_UNASSIGNED", "program_session", "S-20261017-MT", "2026-10-16T18:35:00",
  "沈老师原场次指派随迁移解除", corr=True, cause=id_reloc, educator_id="EDU-SHEN")
E("EDUCATOR_ASSIGNED", "program_session", "S-20261017-PC", "2026-10-16T18:36:00",
  "沈老师平移指派至替代场次（同档期不形成撞档）", corr=True,
  cause=id_reloc, educator_id="EDU-SHEN")
for rid, kind in [("R-REP-01", "replica"), ("R-REP-02", "replica"),
                  ("R-REP-03", "replica"), ("D-DIG-01", "digital")]:
    E("RESOURCE_RESERVED", "movable_replica" if kind == "replica" else "digital_content",
      rid, "2026-10-16T18:40:00",
      f"资源占用随迁移平移至替代场次：{rid}", corr=True, cause=id_reloc,
      resource_kind=kind, session_id="S-20261017-PC", venue_id="V-PC",
      prior_session_id="S-20261017-MT")
E("WAITLIST_ENTRY_PROMOTED", "waitlist_entry", "W-001", "2026-10-16T18:45:00",
  "替代场次无障碍席位增至6，王女士候补转正 5/6", corr=True,
  cause=id_reloc, session_id="S-20261017-PC", party_size=1,
  requested_class="accessible", prior_session_id="S-20261017-MT")
E("GROUP_BOOKING_CREATED", "group_booking", "B-2026-005", "2026-10-16T18:46:00",
  "王女士候补转正生成预约单（无障碍）", corr=True,
  session_id="S-20261017-PC", group_name="王女士一行", seats=1,
  quota_class="accessible", from_waitlist="W-001")
E("BOOKING_CONFIRMED", "group_booking", "B-2026-005", "2026-10-16T18:47:00",
  "王女士无障碍席位确认 5/6，剩余无障碍1席", corr=True,
  session_id="S-20261017-PC", seats=1, quota_class="accessible")
E("TRANSFER_PLANNED", "transfer_order", "T-2026-003", "2026-10-16T19:00:00",
  "排接力运 T-03：三件教具 明堂分馆→平城遗址分馆（次日清晨送达）", corr=True,
  transfer_order_id="T-2026-003",
  resources=["R-REP-01", "R-REP-02", "R-REP-03"],
  from_venue_id="V-MT", to_venue_id="V-PC",
  planned_arrival="2026-10-17T08:45:00+08:00")

# ── 十一、10/17 清晨接力送达，替代场次教具就位 ───────────────────────────
E("TRANSFER_DISPATCHED", "transfer_order", "T-2026-003", "2026-10-17T07:30:00",
  "T-03 发货", corr=True,
  resources=["R-REP-01", "R-REP-02", "R-REP-03"],
  from_venue_id="V-MT", to_venue_id="V-PC")
E("TRANSFER_HANDED_OVER", "transfer_order", "T-2026-003", "2026-10-17T08:40:00",
  "T-03 到达平城遗址分馆并交接", corr=True,
  resources=["R-REP-01", "R-REP-02", "R-REP-03"],
  handed_over_at="V-PC", receiver_role="平城分馆库管员")
E("TRANSFER_ACKNOWLEDGED", "transfer_order", "T-2026-003", "2026-10-17T08:50:00",
  "T-03 签收，三件教具均已到替代场馆", corr=True,
  resources=["R-REP-01", "R-REP-02", "R-REP-03"],
  acknowledged_at="V-PC", inspector_role="平城分馆库管员")
E("TRANSFER_CLOSED", "transfer_order", "T-2026-003", "2026-10-17T09:00:00",
  "T-03 运单关闭", corr=True,
  resources=["R-REP-01", "R-REP-02", "R-REP-03"])

# ── 十二、活动进行：分馆离线，开始/完成只认一次（恢复后补报） ───────────
E("OFFLINE_REPORT_STARTED", "program_session", "S-20261017-PC", "2026-10-17T10:00:00",
  "平城分馆网络中断，本地登记活动准时开始（补报）", corr=True,
  key="S-20261017-PC#started#local-01",
  session_id="S-20261017-PC", venue_id="V-PC", recorded_at="2026-10-17T13:10:00+08:00",
  offline_device="pc-branch-tablet-02")
E("OFFLINE_REPORT_COMPLETED", "program_session", "S-20261017-PC", "2026-10-17T11:35:00",
  "本地登记活动结束（补报），儿童团与轮椅观众均顺利参与", corr=True,
  key="S-20261017-PC#completed#local-01",
  session_id="S-20261017-PC", venue_id="V-PC", recorded_at="2026-10-17T13:10:00+08:00",
  offline_device="pc-branch-tablet-02")
# 同一条“开始”补报因重连抖动被投递两次：幂等键相同，接收侧只认一次（本条将被丢弃）
E("OFFLINE_REPORT_STARTED", "program_session", "S-20261017-PC", "2026-10-17T10:00:00",
  "活动开始补报重投（与首条同幂等键，应丢弃）", corr=True,
  key="S-20261017-PC#started#local-01",
  session_id="S-20261017-PC", venue_id="V-PC", recorded_at="2026-10-17T13:11:00+08:00",
  delivery_attempt=2)

# ── 十三、归还与回运（归还离线补报，只认一次）；数字授权到期 ─────────────
E("RESOURCE_RETURNED", "movable_replica", "R-REP-01", "2026-10-17T13:30:00",
  "主用教具在平城分馆现场点交归还（离线补报）", corr=True,
  key="R-REP-01#returned#S-20261017-PC",
  resource_kind="replica", session_id="S-20261017-PC", returned_at="V-PC",
  recorded_at="2026-10-17T16:20:00+08:00")
E("RESOURCE_RETURNED", "movable_replica", "R-REP-02", "2026-10-17T13:31:00",
  "备用教具现场点交归还（离线补报）", corr=True,
  key="R-REP-02#returned#S-20261017-PC",
  resource_kind="replica", session_id="S-20261017-PC", returned_at="V-PC",
  recorded_at="2026-10-17T16:20:00+08:00")
# 归还补报重投一次：同幂等键，应丢弃
E("RESOURCE_RETURNED", "movable_replica", "R-REP-02", "2026-10-17T13:31:00",
  "备用教具归还补报重投（同幂等键，应丢弃）", corr=True,
  key="R-REP-02#returned#S-20261017-PC",
  resource_kind="replica", session_id="S-20261017-PC", returned_at="V-PC",
  recorded_at="2026-10-17T16:21:00+08:00", delivery_attempt=2)
E("RESOURCE_RETURNED", "movable_replica", "R-REP-03", "2026-10-17T13:32:00",
  "陶俑复制件现场点交归还（系带破损，待回总馆检查）", corr=True,
  resource_kind="replica", session_id="S-20261017-PC",
  returned_at="V-PC", noted_issue="系带脱线")
E("RESOURCE_RETURNED", "digital_content", "D-DIG-01", "2026-10-17T12:00:00",
  "数字走秀场次授权到期收回（可并发，无实体运输）", corr=True,
  resource_kind="digital", session_id="S-20261017-PC")
E("TRANSFER_PLANNED", "transfer_order", "T-2026-004", "2026-10-17T13:35:00",
  "排回运 T-04：三件教具 平城遗址分馆→总馆", corr=True,
  transfer_order_id="T-2026-004",
  resources=["R-REP-01", "R-REP-02", "R-REP-03"],
  from_venue_id="V-PC", to_venue_id="V-MAIN",
  planned_arrival="2026-10-17T16:00:00+08:00")
E("TRANSFER_DISPATCHED", "transfer_order", "T-2026-004", "2026-10-17T13:45:00",
  "T-04 发货", corr=True,
  resources=["R-REP-01", "R-REP-02", "R-REP-03"],
  from_venue_id="V-PC", to_venue_id="V-MAIN")
E("TRANSFER_HANDED_OVER", "transfer_order", "T-2026-004", "2026-10-17T16:00:00",
  "T-04 到达总馆并交接", corr=True,
  resources=["R-REP-01", "R-REP-02", "R-REP-03"],
  handed_over_at="V-MAIN", receiver_role="总馆库房")
E("TRANSFER_ACKNOWLEDGED", "transfer_order", "T-2026-004", "2026-10-17T16:15:00",
  "T-04 签收，进入回馆查验", corr=True,
  resources=["R-REP-01", "R-REP-02", "R-REP-03"],
  acknowledged_at="V-MAIN", inspector_role="总馆库房")
E("CONDITION_RECORDED", "movable_replica", "R-REP-01", "2026-10-17T16:25:00",
  "主用教具回馆查验：完好", corr=True,
  resource_kind="replica", condition_result="合格", inspected_at="V-MAIN")
E("CONDITION_RECORDED", "movable_replica", "R-REP-02", "2026-10-17T16:26:00",
  "备用教具回馆查验：完好", corr=True,
  resource_kind="replica", condition_result="合格", inspected_at="V-MAIN")
E("CONDITION_RECORDED", "movable_replica", "R-REP-03", "2026-10-17T16:27:00",
  "陶俑复制件回馆查验：系带脱线，需修复，暂不可再用", corr=True,
  resource_kind="replica", condition_result="不合格", inspected_at="V-MAIN",
  issue="系带脱线")
E("RESOURCE_CLEARED", "movable_replica", "R-REP-01", "2026-10-17T16:35:00",
  "主用教具复检合格，可再次使用", corr=True, resource_kind="replica")
E("RESOURCE_CLEARED", "movable_replica", "R-REP-02", "2026-10-17T16:36:00",
  "备用教具复检合格，可再次使用", corr=True, resource_kind="replica")
E("RESOURCE_QUARANTINED", "movable_replica", "R-REP-03", "2026-10-17T16:37:00",
  "陶俑复制件隔离待修（待检查），修复复检前不得再排用", corr=True,
  resource_kind="replica", reason="系带脱线")
E("TRANSFER_CLOSED", "transfer_order", "T-2026-004", "2026-10-17T16:40:00",
  "T-04 运单关闭", corr=True,
  resources=["R-REP-01", "R-REP-02", "R-REP-03"])
E("SESSION_CLOSED", "program_session", "S-20261017-PC", "2026-10-17T17:00:00",
  "替代场次归档关闭", corr=True, session_id="S-20261017-PC")

# ── 十四、反馈归档 ───────────────────────────────────────────────────────
E("FEEDBACK_RECORDED", "activity_feedback", "F-001", "2026-10-19T10:00:00",
  "城区三小带队老师反馈：替代场馆通知及时，轮椅通道与无障碍席位充足",
  corr=True, session_id="S-20261017-PC", from_role="带队老师",
  ratings={"内容": 5, "组织": 5, "无障碍": 5},
  note="闭馆当天一早就收到了新地址与席位确认")
E("FEEDBACK_RECORDED", "activity_feedback", "F-002", "2026-10-19T11:00:00",
  "阳光之家反馈：数字走秀在教具迟到预案中起到作用",
  corr=True, session_id="S-20261017-PC", from_role="家属代表",
  ratings={"内容": 5, "组织": 4, "无障碍": 5})

# ── 十五、明堂分馆恢复；真品复检合格重回可预约 ───────────────────────────
E("ENVIRONMENT_CLEARED", "venue", "V-MT", "2026-10-18T09:00:00",
  "明堂分馆湿度恢复至55%，环境达标", corr=True,
  venue_id="V-MT", reading={"temperature_c": 20.5, "humidity_pct": 55})
E("RESOURCE_CLEARED", "collection_resource", "R-AUTH-01", "2026-10-18T09:10:00",
  "真品陶俑复检通过，恢复可借调状态", corr=True,
  resource_kind="authentic_object")
E("VENUE_BACK_IN_SERVICE", "venue", "V-MT", "2026-10-18T10:00:00",
  "明堂分馆供暖修复完成，恢复开放", corr=True,
  venue_id="V-MT", resolved_cause_event=id_out)

# ── 十六、讲解/展陈/材料发布新版：旧场次还原结果仍指向 v1 ────────────────
E("INTERPRETATION_PUBLISHED", "interpretation", "INT-BEIWEI-V2", "2026-10-20T09:00:00",
  "发布讲解口径 v2（吸收最新服制研究），旧版保留",
  interpretation_id="INT-BEIWEI", version_tag="v2",
  title="平城鲜卑服制再考", supersedes="INT-BEIWEI-V1")
E("EXHIBIT_VERSION_PUBLISHED", "exhibit_version", "EX-BEIWEI-V2", "2026-10-21T09:00:00",
  "发布《北魏服饰》展陈版本 v2", exhibit_id="EX-BEIWEI",
  version_tag="v2", title="北魏服饰展陈（修订版）")
E("EXHIBIT_VERSION_SUPERSEDED", "exhibit_version", "EX-BEIWEI-V1", "2026-10-21T09:05:00",
  "展陈 v1 被 v2 更替（内容保留，供历史场次还原）",
  exhibit_id="EX-BEIWEI", version_tag="v1", superseded_by="EX-BEIWEI-V2")
E("COURSE_MATERIAL_PUBLISHED", "course_material", "CM-BEIWEI-RESTORE", "2026-10-22T09:00:00",
  "课程材料更新为 v2（新增数字走秀操作卡）", course_code="CM-BEIWEI-RESTORE",
  version_tag="v2", title="北魏服饰复原课",
  materials=["讲义v2", "穿戴耗材清单v2", "数字走秀操作卡v2"], supersedes="v1")

# ── 十七、破损复制件修复复检合格，回到可再次使用 ─────────────────────────
E("RESOURCE_CLEARED", "movable_replica", "R-REP-03", "2026-10-22T15:00:00",
  "陶俑复制件系带修复并复检合格，可再次使用",
  resource_kind="replica", repair_note="系带重新缝合加固")

# Python 排序本身稳定：同刻保持插入顺序
_events.sort(key=lambda e: e["occurred_at"])

# 同幂等键第二条起为重复投递：不进入正式事件流，单独列出供"只认一次"联调
seen_keys: set[str] = set()
canonical: list[dict] = []
duplicates: list[dict] = []
for e in _events:
    k = e.get("idempotency_key")
    if k is not None and k in seen_keys:
        duplicates.append(e)
    else:
        if k is not None:
            seen_keys.add(k)
        canonical.append(e)

ref_to_id: dict[str, str] = {}
for i, e in enumerate(canonical, start=1):
    eid = f"{e['occurred_at'][2:10].replace('-', '')}-{i:03d}"
    ref_to_id[e["_ref"]] = eid
    e["event_id"] = eid

# 正式事件流内按聚合重新连续编号，保证 version 与发生时间顺序一致
agg_ver: dict[str, int] = {}
for e in canonical:
    v = agg_ver.get(e["aggregate_id"], 0) + 1
    agg_ver[e["aggregate_id"]] = v
    e["version"] = v

# 重复投递：是同一条逻辑事件的重传（event_id 不同、幂等键相同、版本与首条一致），
# 接收侧必须丢弃
key_to_version = {e["idempotency_key"]: e["version"]
                  for e in canonical if e.get("idempotency_key")}
for j, d in enumerate(duplicates, start=1):
    d["event_id"] = f"DUP-{j:02d}"
    d["version"] = key_to_version[d["idempotency_key"]]

def finalize(e: dict) -> dict:
    out = {k: v for k, v in e.items() if not k.startswith("_")}
    if "_cause_ref" in e:
        out["caused_by_event_id"] = ref_to_id[e["_cause_ref"]]
    return out

doc = {
    "description": "北魏服饰复原课跨馆资源接力完整事件流（含异常重排、保障名额、离线补报、替代场次、版本固化）。duplicate_deliveries 中的记录信封有效但因幂等键重复必须被接收侧丢弃。",
    "correlation_id": CORR,
    "events": [finalize(e) for e in canonical],
    "duplicate_deliveries": [finalize(d) for d in duplicates],
}
OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"wrote {len(canonical)} events + {len(duplicates)} duplicate deliveries to {OUT}")
