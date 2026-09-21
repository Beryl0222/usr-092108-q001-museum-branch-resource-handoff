"""事件流投影：资源状态、场次还原、预约页四问与业务不变量。

输入为已经过幂等去重的事件（见 validator.deduplicate），按 occurred_at 排序。
所有状态都从事件重放得到，不另存可变表，保证"从任何一场活动都能还原"。
"""

from dataclasses import dataclass, field
from datetime import datetime

from .validator import _parse_dt, CST

MIN_TS = datetime.min.replace(tzinfo=CST)
MAX_TS = datetime.max.replace(tzinfo=CST)

GENERAL = "general"
CHILDREN = "children"
ACCESSIBLE = "accessible"


def _p(event: dict) -> dict:
    return event.get("payload") or {}


@dataclass
class _Order:
    order_id: str
    resources: list[str]
    from_venue: str | None = None
    to_venue: str | None = None
    phase: str = "planned"          # planned/dispatched/delayed/handed/acknowledged/closed
    phase_at: datetime | None = None
    delayed: bool = False


@dataclass
class _Resource:
    kind: str
    home_venue: str | None
    quarantined: bool = False
    reservation: dict | None = None     # 最新有效预约 {session_id, venue_id}
    returned: bool = False
    last_clear: datetime | None = None
    last_return: datetime | None = None
    last_condition: dict | None = None
    location: str | None = None
    orders: dict[str, _Order] = field(default_factory=dict)


class RelayProjection:
    def __init__(self, events: list[dict], as_of: datetime | None = None):
        self.events = events
        self.as_of = as_of
        self.venues: dict[str, dict] = {}
        self.resources: dict[str, _Resource] = {}
        self.orders: dict[str, _Order] = {}
        self.educators: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}
        self.by_id: dict[str, dict] = {}
        self.children: dict[str, list[str]] = {}
        self._replay()

    # ── 重放 ──────────────────────────────────────────────────────────────
    def _replay(self) -> None:
        for e in self.events:
            ts = _parse_dt(e["occurred_at"])
            if self.as_of is not None and ts > self.as_of:
                break
            self.by_id[e["event_id"]] = e
            cause = e.get("caused_by_event_id")
            if cause:
                self.children.setdefault(cause, []).append(e["event_id"])
            et, at, agg, p = e["event_type"], e["aggregate_type"], e["aggregate_id"], _p(e)
            if et == "VENUE_REGISTERED":
                self.venues[agg] = {"venue_id": agg, "name": p.get("branch_name"),
                                    "out_of_service": False, "alerts": []}
            elif et == "VENUE_TAKEN_OUT_OF_SERVICE":
                self.venues.get(agg, {}).update(out_of_service=True)
            elif et == "VENUE_BACK_IN_SERVICE":
                self.venues.get(agg, {}).update(out_of_service=False)
            elif et == "ENVIRONMENT_ALERT_RAISED":
                self.venues.get(agg, {}).get("alerts", []).append(
                    {"raised": ts, "cleared": None, "reading": p.get("reading")})
            elif et == "ENVIRONMENT_CLEARED":
                for a in reversed(self.venues.get(agg, {}).get("alerts", [])):
                    if a["cleared"] is None:
                        a["cleared"] = ts
                        break
            elif et in ("RESOURCE_REGISTERED",):
                self.resources[agg] = _Resource(
                    kind=p.get("resource_kind", "replica"),
                    home_venue=p.get("home_venue_id"),
                    location=p.get("home_venue_id"))
            elif at in ("collection_resource", "movable_replica", "digital_content"):
                self._apply_resource_event(agg, et, ts, p)
            elif at == "transfer_order":
                self._apply_order_event(agg, et, ts, p)
            elif et == "EDUCATOR_REGISTERED":
                self.educators[agg] = {
                    "name": p.get("name"),
                    "courses": set(p.get("qualified_courses", [])),
                    "valid_until": _parse_dt(p.get("qualification_valid_until", ""))
                    if p.get("qualification_valid_until") else None}
            elif et == "SESSION_OPENED":
                self.sessions[agg] = {
                    "session_id": agg, "venue_id": p.get("venue_id"),
                    "course_code": p.get("course_code"),
                    "start": _parse_dt(p.get("scheduled_start", "")),
                    "end": _parse_dt(p.get("scheduled_end", "")),
                    "capacity": p.get("capacity"),
                    "protected_children_seats": p.get("protected_children_seats", 0),
                    "accessible_seats": p.get("accessible_seats", 0),
                    "original_session_id": p.get("original_session_id"),
                    "replacement_session_id": None, "pinned": None,
                    "educator_ids": [], "alerts": []}
            elif et == "SESSION_RELOCATED":
                s = self.sessions.get(agg)
                if s:
                    s["replacement_session_id"] = p.get("replacement_session_id")
            elif et == "SESSION_CONTENT_PINNED":
                s = self.sessions.get(agg)
                if s:
                    s["pinned"] = {
                        "interpretation_id": p.get("interpretation_id"),
                        "interpretation_version": p.get("interpretation_version"),
                        "exhibit_id": p.get("exhibit_id"),
                        "exhibit_version": p.get("exhibit_version"),
                        "course_material_version": p.get("course_material_version")}

    def _apply_resource_event(self, rid: str, et: str, ts: datetime, p: dict) -> None:
        r = self.resources.get(rid)
        if r is None:
            return
        if et == "RESOURCE_RESERVED":
            if p.get("session_id"):
                r.reservation = {"session_id": p["session_id"], "venue_id": p.get("venue_id")}
            r.returned = False
        elif et == "RESOURCE_RESERVATION_RELEASED":
            if r.reservation and r.reservation.get("session_id") == p.get("session_id"):
                r.reservation = None
        elif et == "RESOURCE_QUARANTINED":
            r.quarantined = True
        elif et == "RESOURCE_CLEARED":
            r.quarantined = False
            r.last_clear = ts
        elif et == "RESOURCE_RETURNED":
            r.returned = True
            r.last_return = ts
            if r.kind == "digital":
                r.reservation = None          # 授权到期，即时回到可授权
            elif r.reservation and r.reservation.get("session_id") == p.get("session_id"):
                r.reservation = None
        elif et == "CONDITION_RECORDED" and "condition_result" in p:
            r.last_condition = {"at": ts, "result": p.get("condition_result"),
                                "venue_id": p.get("inspected_at")}

    def _apply_order_event(self, oid: str, et: str, ts: datetime, p: dict) -> None:
        order = self.orders.get(oid)
        if order is None:
            order = _Order(order_id=oid, resources=list(p.get("resources", [])),
                           from_venue=p.get("from_venue_id"), to_venue=p.get("to_venue_id"))
            self.orders[oid] = order
            for rid in order.resources:
                if rid in self.resources:
                    self.resources[rid].orders[oid] = order
        if p.get("to_venue_id"):
            order.to_venue = p["to_venue_id"]
        phase_map = {"TRANSFER_PLANNED": "planned", "TRANSFER_DISPATCHED": "dispatched",
                     "TRANSFER_DELAYED": "delayed", "TRANSFER_HANDED_OVER": "handed",
                     "TRANSFER_ACKNOWLEDGED": "acknowledged", "TRANSFER_CLOSED": "closed"}
        if et in phase_map:
            order.phase = phase_map[et]
            order.phase_at = ts
            if et == "TRANSFER_DELAYED":
                order.delayed = True
        if et == "TRANSFER_HANDED_OVER":
            for rid in order.resources:
                if rid in self.resources:
                    self.resources[rid].location = order.to_venue
        if et == "TRANSFER_ACKNOWLEDGED":
            for rid in order.resources:
                if rid in self.resources:
                    self.resources[rid].location = p.get("acknowledged_at", order.to_venue)

    # ── 资源状态（领域模型 §8） ───────────────────────────────────────────
    def resource_status(self, rid: str) -> dict:
        r = self.resources[rid]
        open_orders = [o for o in r.orders.values() if o.phase != "closed"]
        latest_order = max(r.orders.values(), key=lambda o: o.phase_at or MIN_TS,
                           default=None)
        state, detail = "available", "可预约"
        if r.quarantined:
            state, detail = "pending_inspection", "待检查（隔离中）"
        elif r.returned:
            if r.kind == "digital":
                state, detail = "available", "可授权（数字内容无实体周转）"
            elif r.last_clear and r.last_clear >= (r.last_return or MIN_TS):
                state, detail = "reusable", "可再次使用（归还且复检合格）"
            else:
                state, detail = "pending_inspection", "待检查（已归还，等待复检）"
        elif any(o.phase in ("dispatched", "delayed") for o in open_orders):
            delayed = [o.order_id for o in open_orders if o.delayed]
            state, detail = "in_transit", ("途中（运输迟延：%s）" % ",".join(delayed)
                                           if delayed else "途中")
        elif any(o.phase == "handed" for o in open_orders):
            state, detail = "pending_inspection", "待检查（已到场，未签收）"
        elif r.reservation:
            if latest_order and latest_order.phase == "acknowledged":
                state, detail = "in_use", "使用中（已到场签收，待开课/进行中）"
            elif any(o.phase == "planned" for o in open_orders):
                state, detail = "reserved", "已预约（运输已排未发）"
            else:
                state, detail = "reserved", "已预约（待排运/数字授权待生效）"
        return {"resource_id": rid, "kind": r.kind, "state": state, "detail": detail,
                "location": r.location, "reservation": r.reservation,
                "condition": r.last_condition and r.last_condition["result"]}

    def resources_by_state(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for rid in self.resources:
            out.setdefault(self.resource_status(rid)["state"], []).append(rid)
        return out

    # ── 场次还原（领域模型 §7） ───────────────────────────────────────────
    def _effective_session_id(self, session_id: str) -> str:
        s = self.sessions.get(session_id)
        if s and s["replacement_session_id"]:
            return s["replacement_session_id"]
        return session_id

    def session_view(self, session_id: str) -> dict:
        """沿事件流还原一场活动：物品、人员、场地、内容、预约、候补、异常、反馈。"""
        original = session_id
        effective = self._effective_session_id(session_id)
        ids = {original}
        if effective != original:
            ids.add(effective)

        resources, educators, feedback, offline = [], [], [], []
        transfers, anomalies, booking_map, waitlist_map = set(), [], {}, {}
        for e in self.events:
            et, p = e["event_type"], _p(e)
            sid = p.get("session_id")
            if et in ("RESOURCE_RESERVED", "RESOURCE_RESERVATION_RELEASED",
                      "RESOURCE_RETURNED") and sid in ids:
                resources.append({"event_id": e["event_id"], "type": et,
                                  "resource_id": e["aggregate_id"],
                                  "resource_kind": p.get("resource_kind"),
                                  "venue_id": p.get("venue_id"),
                                  "replaces": p.get("replaces_resource"),
                                  "caused_by": e.get("caused_by_event_id")})
            elif et in ("EDUCATOR_ASSIGNED", "EDUCATOR_UNASSIGNED") and e["aggregate_id"] in ids:
                educators.append({"event_id": e["event_id"], "type": et,
                                  "educator_id": p.get("educator_id"),
                                  "caused_by": e.get("caused_by_event_id")})
            elif et == "BOOKING_CONFIRMED" and sid in ids:
                # 平移预约在原场与替代场各确认一次，按预约号只保留最终一条
                booking_map[e["aggregate_id"]] = {"booking_id": e["aggregate_id"],
                                                  "seats": p.get("seats"),
                                                  "quota_class": p.get("quota_class"),
                                                  "from_waitlist": p.get("from_waitlist"),
                                                  "session_id": sid}
            elif et == "BOOKING_CANCELLED" and sid in ids:
                booking_map.pop(e["aggregate_id"], None)
            elif et in ("WAITLIST_ENTRY_ADDED", "WAITLIST_ENTRY_PROMOTED",
                        "WAITLIST_ENTRY_EXPIRED") and sid in ids:
                # 同一候补条目随生命周期折叠为最终状态
                waitlist_map[e["aggregate_id"]] = {
                    "entry_id": e["aggregate_id"], "state": et.split("_")[-1].lower(),
                    "requested_class": p.get("requested_class"),
                    "party_size": p.get("party_size")}
            elif et == "FEEDBACK_RECORDED" and sid in ids:
                feedback.append({"feedback_id": e["aggregate_id"], "from_role": p.get("from_role")})
            elif et == "TRANSFER_PLANNED" and (
                    set(p.get("resources", [])) & {x["resource_id"] for x in resources}):
                transfers.add(e["aggregate_id"])
            elif et in ("OFFLINE_REPORT_STARTED", "OFFLINE_REPORT_COMPLETED") and e["aggregate_id"] in ids:
                offline.append({"type": et, "at": e["occurred_at"],
                                "idempotency_key": e.get("idempotency_key")})
            elif et in ("ENVIRONMENT_ALERT_RAISED", "VENUE_TAKEN_OUT_OF_SERVICE",
                        "TRANSFER_DELAYED") and e.get("correlation_id"):
                if self._descendant_touches(e["event_id"], ids):
                    anomalies.append(e["event_id"])

        s_orig = self.sessions.get(original, {})
        s_eff = self.sessions.get(effective, {})
        venue_events = []
        for e in self.events:
            if e["aggregate_id"] in (s_orig.get("venue_id"), s_eff.get("venue_id")) and \
                    e["event_type"] in ("ENVIRONMENT_ALERT_RAISED", "ENVIRONMENT_CLEARED",
                                        "VENUE_TAKEN_OUT_OF_SERVICE", "VENUE_BACK_IN_SERVICE"):
                venue_events.append({"event_id": e["event_id"], "type": e["event_type"],
                                     "venue_id": e["aggregate_id"]})
        return {"session_id": original, "effective_session_id": effective,
                "relocated": effective != original,
                "venue": self._venue_brief(s_eff.get("venue_id")),
                "original_venue": self._venue_brief(s_orig.get("venue_id")),
                "content_pinned": s_eff.get("pinned") or s_orig.get("pinned"),
                "scheduled_start": s_eff.get("start") and s_eff["start"].isoformat(),
                "resources": resources, "educators": educators,
                "bookings": list(booking_map.values()),
                "waitlist": list(waitlist_map.values()),
                "transfers": sorted(transfers),
                "venue_events": venue_events, "anomaly_roots": sorted(set(anomalies)),
                "offline_reports": offline, "feedback": feedback}

    def _descendant_touches(self, root_id: str, session_ids: set[str]) -> bool:
        for cid in self.children.get(root_id, []):
            c = self.by_id.get(cid, {})
            if _p(c).get("session_id") in session_ids:
                return True
            if self._descendant_touches(cid, session_ids):
                return True
        return False

    def _venue_brief(self, vid: str | None) -> dict | None:
        v = self.venues.get(vid)
        return None if v is None else {"venue_id": vid, "name": v["name"],
                                       "out_of_service": v["out_of_service"]}

    # ── 预约页面四问 ──────────────────────────────────────────────────────
    def booking_page(self, session_id: str) -> dict:
        """带队老师最关心的四件事：分馆、教具、无障碍名额、替代场次。

        按场次开场时刻切片重放：迁移后页面显示替代场馆与开场时教具就位状态，
        与现场一致；归还等收场事件不会让页面"教具消失"。
        """
        effective = self._effective_session_id(session_id)
        full = self.sessions[effective]
        view = RelayProjection(self.events, as_of=full["start"]) if full.get("start") else self
        s = view.sessions[effective]
        confirmed = view._confirmed_seats(effective)
        replicas, digital, authentic = [], [], []
        for rid, r in view.resources.items():
            if not r.reservation or r.reservation.get("session_id") != effective:
                continue
            item = view._arrival_item(rid, r, s["venue_id"])
            {"replica": replicas, "digital": digital,
             "authentic_object": authentic}[r.kind].append(item)
        accessible_cap = s["accessible_seats"]
        accessible_used = confirmed[ACCESSIBLE]
        return {"session_id": session_id, "effective_session_id": effective,
                "relocated": effective != session_id,
                "branch": self._venue_brief(s["venue_id"]),
                "teaching_aids": {"arrived": sum(1 for x in replicas if x["arrived"]),
                                  "total": len(replicas), "items": replicas},
                "digital_contents": digital,
                "authentic_objects": authentic,
                "accessible_seats": {"capacity": accessible_cap, "confirmed": accessible_used,
                                     "remaining": accessible_cap - accessible_used},
                "children_seats": {"capacity": s["protected_children_seats"],
                                   "confirmed": confirmed[CHILDREN],
                                   "remaining": s["protected_children_seats"] - confirmed[CHILDREN]},
                "replacement": (self._venue_brief(s["venue_id"])
                                if effective != session_id else None)}

    def _arrival_item(self, rid: str, r: _Resource, venue_id: str) -> dict:
        arrived = any(o.phase in ("acknowledged", "closed") and o.to_venue == venue_id
                      for o in r.orders.values())
        if r.kind == "digital":
            arrived = r.reservation is not None
        return {"resource_id": rid, "kind": r.kind, "arrived": arrived,
                "location": r.location,
                "condition": r.last_condition and r.last_condition["result"]}

    def _confirmed_seats(self, session_id: str) -> dict[str, int]:
        totals = {GENERAL: 0, CHILDREN: 0, ACCESSIBLE: 0}
        for e in self.events:
            p = _p(e)
            if p.get("session_id") != session_id:
                continue
            if e["event_type"] == "BOOKING_CONFIRMED":
                totals[p.get("quota_class", GENERAL)] += p.get("seats", 0)
            elif e["event_type"] == "BOOKING_CANCELLED":
                totals[p.get("quota_class", GENERAL)] -= p.get("seats", 0)
        return totals

    # ── 异常因果链 ───────────────────────────────────────────────────────
    def anomaly_chain(self, root_event_id: str) -> list[dict]:
        out = []
        stack = [(root_event_id, 0)]
        while stack:
            eid, depth = stack.pop(0)
            e = self.by_id.get(eid)
            if e:
                out.append({"event_id": eid, "depth": depth,
                            "event_type": e["event_type"], "summary": e["summary"]})
                stack[0:0] = [(c, depth + 1) for c in self.children.get(eid, [])]
        return out

    # ── 业务不变量（验收） ───────────────────────────────────────────────
    def check_invariants(self) -> list[str]:
        errors: list[str] = []
        errors += self._check_quotas()
        errors += self._check_authentic_environment()
        errors += self._check_transport_contention()
        errors += self._check_educators()
        errors += self._check_content_versions()
        errors += self._check_replacements()
        return sorted(set(errors))

    def _check_quotas(self) -> list[str]:
        errors = []
        for sid, s in self.sessions.items():
            used = self._confirmed_seats(sid)
            if used[CHILDREN] > s["protected_children_seats"]:
                errors.append(f"{sid}：儿童保障名额超用 {used[CHILDREN]}/{s['protected_children_seats']}")
            if used[ACCESSIBLE] > s["accessible_seats"]:
                errors.append(f"{sid}：无障碍名额超用 {used[ACCESSIBLE]}/{s['accessible_seats']}")
            general_budget = s["capacity"] - s["protected_children_seats"] - s["accessible_seats"]
            if used[GENERAL] > general_budget:
                errors.append(f"{sid}：普通席超用 {used[GENERAL]}/{general_budget}")
        return errors

    def _check_authentic_environment(self) -> list[str]:
        errors = []
        for rid, r in self.resources.items():
            if r.kind != "authentic_object" or not r.reservation:
                continue
            venue = self.venues.get(r.reservation.get("venue_id"))
            if venue and any(a["cleared"] is None for a in venue["alerts"]):
                errors.append(f"{rid}：真品在环境告警未解除的场馆 {venue['venue_id']} 仍处于预约状态")
        return errors

    def _check_transport_contention(self) -> list[str]:
        errors = []
        for rid, r in self.resources.items():
            if r.kind == "digital":
                continue
            # 同一时刻只允许一个未闭合运单：按发货→关闭区间两两判断
            intervals = []
            for o in r.orders.values():
                dispatched = self._phase_time(o.order_id, "TRANSFER_DISPATCHED")
                closed = self._phase_time(o.order_id, "TRANSFER_CLOSED")
                if dispatched:
                    intervals.append((o.order_id, dispatched, closed or MAX_TS))
            intervals.sort(key=lambda x: x[1])
            for (a, a0, a1), (b, b0, b1) in zip(intervals, intervals[1:]):
                if b0 < a1:
                    errors.append(f"{rid}：运单 {a} 未闭合即被 {b} 争用（运力重叠）")
        return errors

    def _phase_time(self, oid: str, et: str) -> datetime | None:
        for e in self.events:
            if e["aggregate_id"] == oid and e["event_type"] == et:
                return _parse_dt(e["occurred_at"])
        return None

    def _check_educators(self) -> list[str]:
        errors = []
        assignments: dict[str, list[tuple[dict, dict]]] = {}
        for e in self.events:
            if e["event_type"] == "EDUCATOR_ASSIGNED":
                sid = e["aggregate_id"]
                s = self.sessions.get(sid)
                edu = self.educators.get(_p(e).get("educator_id"))
                if s and edu:
                    if s["course_code"] not in edu["courses"]:
                        errors.append(f"{sid}：讲师 {edu['name']} 无课程 {s['course_code']} 资质")
                    elif edu["valid_until"] and s["start"] and edu["valid_until"] < s["start"]:
                        errors.append(f"{sid}：讲师 {edu['name']} 资质已过期")
                    assignments.setdefault(_p(e)["educator_id"], []).append((e, s))
            if e["event_type"] == "EDUCATOR_UNASSIGNED":
                for eid, lst in assignments.items():
                    if eid == _p(e).get("educator_id"):
                        lst.append((e, self.sessions.get(e["aggregate_id"], {})))
        # 同讲师不得同时挂在两个进行中场次（解除事件之后不计）
        for eid, lst in assignments.items():
            active: list[dict] = []
            for e, s in sorted(lst, key=lambda x: _parse_dt(x[0]["occurred_at"])):
                if e["event_type"] == "EDUCATOR_UNASSIGNED":
                    active = [x for x in active if x["session_id"] != e["aggregate_id"]]
                else:
                    for a in active:
                        if a["start"] and s.get("start") and a["end"] and s.get("start") and \
                                s["start"] < a["end"] and a["start"] < s["end"]:
                            errors.append(f"讲师 {eid} 在 {a['session_id']} 与 {s['session_id']} 撞档")
                    active.append(s)
        return errors

    def _check_content_versions(self) -> list[str]:
        errors = []
        interp_pair = {(_p(e).get("interpretation_id"), _p(e).get("version_tag"))
                       for e in self.events if e["event_type"] == "INTERPRETATION_PUBLISHED"}
        exhibits = {(_p(e).get("exhibit_id"), _p(e).get("version_tag"))
                    for e in self.events if e["event_type"] == "EXHIBIT_VERSION_PUBLISHED"}
        materials = {(_p(e).get("course_code") or e["aggregate_id"], _p(e).get("version_tag"))
                     for e in self.events if e["event_type"] == "COURSE_MATERIAL_PUBLISHED"}
        held = {e["aggregate_id"] for e in self.events
                if e["event_type"] == "OFFLINE_REPORT_STARTED"}
        for sid, s in self.sessions.items():
            if sid in held and not s["pinned"]:
                errors.append(f"{sid}：活动已开始但未固化讲解/展陈/材料版本")
            pin = s["pinned"]
            if not pin:
                continue
            if (pin["interpretation_id"], pin["interpretation_version"]) not in interp_pair:
                errors.append(f"{sid}：固化的讲解版本 {pin['interpretation_id']}@{pin['interpretation_version']} 不存在")
            if (pin["exhibit_id"], pin["exhibit_version"]) not in exhibits:
                errors.append(f"{sid}：固化的展陈版本 {pin['exhibit_id']}@{pin['exhibit_version']} 不存在")
            if (s["course_code"], pin["course_material_version"]) not in materials:
                errors.append(f"{sid}：固化的材料版本 {s['course_code']}@{pin['course_material_version']} 不存在")
        return errors

    def _check_replacements(self) -> list[str]:
        errors = []
        for sid, s in self.sessions.items():
            rid = s["replacement_session_id"]
            if not rid:
                continue
            rep = self.sessions.get(rid)
            if not rep:
                errors.append(f"{sid}：替代场次 {rid} 未开仓")
                continue
            if rep["accessible_seats"] < s["accessible_seats"]:
                errors.append(f"{sid}：替代场次无障碍容量 {rep['accessible_seats']} < 原场 {s['accessible_seats']}")
            if rep["protected_children_seats"] < s["protected_children_seats"]:
                errors.append(f"{sid}：替代场次儿童保障容量不足")
            if not rep["pinned"]:
                errors.append(f"{rid}：替代场次未固化内容版本")
            if not any(e["event_type"] == "EDUCATOR_ASSIGNED" and e["aggregate_id"] == rid
                       for e in self.events):
                errors.append(f"{rid}：替代场次未指派讲师")
            # 平移预约须在替代场次重新确认
            for e in self.events:
                if e["event_type"] == "SESSION_OPENED" and e["aggregate_id"] == rid:
                    for bid in _p(e).get("transferred_bookings", []):
                        if not any(x["event_type"] == "BOOKING_CONFIRMED"
                                   and x["aggregate_id"] == bid
                                   and _p(x).get("session_id") == rid for x in self.events):
                            errors.append(f"{rid}：平移预约 {bid} 未在替代场次重新确认")
            # 开课时教具须在替代场馆签收
            for r_id, r in self.resources.items():
                if r.kind == "replica" and r.reservation and r.reservation.get("session_id") == rid:
                    arrived = any(o.to_venue == rep["venue_id"]
                                  and o.phase in ("acknowledged", "closed")
                                  and (not o.phase_at or not rep["start"] or o.phase_at <= rep["start"])
                                  for o in r.orders.values())
                    if not arrived:
                        errors.append(f"{rid}：开课时教具 {r_id} 未送达 {rep['venue_id']}")
        return errors
