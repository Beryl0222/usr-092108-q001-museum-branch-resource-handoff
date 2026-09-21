"""事件重放与只读投影。

所有状态都由领域事件重放得到，不做就地改写；业务更正通过后继事件体现。
分馆离线后补报的事件按 ``occurred_at``（接收时刻）入账，其业务发生时刻
保留在 payload.business_time 中。

投影提供验收所需的四类查询：
- ``session_view``：从任一场次还原物品、人员、场地与异常交接；
- ``booking_page``：预约页面所示地点、条件、剩余名额；
- ``headquarters_board``：总馆识别在途中 / 待检查 / 可再次使用的资源；
- ``resource_trace``：单件资源的完整时间线。
"""

from collections import defaultdict

from .validator import validate_event_full


class ReplayError(ValueError):
    pass


class Replay:
    def __init__(self, events: list[dict], strict: bool = True,
                 as_of: str | None = None) -> None:
        self.issues: list[str] = []
        self.duplicate_events: list[dict] = []  # 被幂等挡下的重复投递

        prepared = self._prepare(events, strict, as_of)
        self.as_of = as_of
        self.events = prepared["events"]
        self.offline_seen: dict[tuple[str, str], dict] = prepared["offline_seen"]

        self.resources: dict[str, dict] = {}
        self.venues: dict[str, dict] = {}
        self.slots: dict[str, dict] = {}
        self.transfers: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}
        self.instructors: dict[str, dict] = {}
        self.bookings: dict[str, dict] = {}
        self.waitlists: dict[str, dict] = {}
        self.versions: dict[str, dict] = {}  # 展陈/材料/讲解解释的所有版本
        self.loans: dict[str, dict] = {}
        self.feedback: list[dict] = []
        self.offline_reports: list[dict] = []

        for event in self.events:
            self._apply(event)

    # -- 入流准备：校验、排序、幂等去重 -------------------------------------

    def _prepare(self, events: list[dict], strict: bool,
                 as_of: str | None) -> dict:
        accepted: list[dict] = []
        seen_event_ids: set[str] = set()
        offline_seen: dict[tuple[str, str], dict] = {}

        for raw in events:
            errors = validate_event_full(raw)
            if errors:
                msg = f"事件 {raw.get('event_id', '?')} 校验失败：{'；'.join(errors)}"
                if strict:
                    raise ReplayError(msg)
                self.issues.append(msg)
                continue

            if as_of is not None and raw["occurred_at"] > as_of:
                continue  # 时点重放：只看到该时刻之前已发生的事实

            # 信封事件标识全局唯一：重投同一条不重复生效。
            if raw["event_id"] in seen_event_ids:
                self.duplicate_events.append(raw)
                continue
            seen_event_ids.add(raw["event_id"])

            # 离线补报三事件：同一业务事实（event_type + dedupe_key）只认一次。
            etype = raw["event_type"]
            if etype in _OFFLINE:
                key = (etype, raw["dedupe_key"])
                if key in offline_seen:
                    self.duplicate_events.append(raw)
                    continue
                offline_seen[key] = {"event_id": raw["event_id"],
                                     "business_time": raw["payload"].get("business_time")}
            accepted.append(raw)

        accepted.sort(key=lambda e: (e["occurred_at"], e["version"], e["event_id"]))
        return {"events": accepted, "offline_seen": offline_seen}

    # -- 状态转移 -----------------------------------------------------------

    def _apply(self, event: dict) -> None:
        etype = event["event_type"]
        handler = getattr(self, f"_on_{etype.lower()}", None)
        if handler is None:
            # 目录里有、但投影暂不关心的事件不报错（前向兼容）。
            return
        handler(event)

    def _p(self, event: dict) -> dict:
        return event.get("payload", {})

    # 资源台账
    def _on_resource_registered(self, e: dict) -> None:
        p = self._p(e)
        self.resources[p["resource_id"] or e["aggregate_id"]] = {
            "resource_id": p.get("resource_id", e["aggregate_id"]),
            "resource_kind": p["resource_kind"],
            "title": p["title"],
            "home_venue_id": p["home_venue_id"],
            "status": "available",
            "holds": [],
            "location_venue_id": p["home_venue_id"],
            "session_id": None,
            "availability": "at_home",
            "timeline": [_at(e, "登记建档")],
        }

    def _on_resource_reserved(self, e: dict) -> None:
        p = self._p(e)
        rid = p.get("resource_id", e["aggregate_id"])
        res = self.resources.setdefault(rid, _skeleton_resource(rid))
        res["session_id"] = p["session_id"]
        sess = self.sessions.setdefault(p["session_id"], _skeleton_session(p["session_id"]))
        sess["resources"][rid] = res.get("resource_kind", "unknown")
        # 历史上曾为该场预留的资源不随后续撤出而消失（撤改痕迹在 replans 中）。
        sess.setdefault("resource_history", {})[rid] = res.get("resource_kind", "unknown")
        res["timeline"].append(_at(e, f"预留给场次 {p['session_id']}"))

    def _on_condition_recorded(self, e: dict) -> None:
        p = self._p(e)
        rid = p.get("resource_id", e["aggregate_id"])
        res = self.resources.setdefault(rid, _skeleton_resource(rid))
        res["holds"] = list(p.get("holds", []))
        res.setdefault("condition_log", []).append(
            {"recorded_at": p["recorded_at"], "holds": p["holds"],
             "assessment": p["assessment"], "event_id": e["event_id"]})
        res["timeline"].append(_at(e, f"状况检查：{p['assessment']}"))

    def _on_resource_blocked(self, e: dict) -> None:
        p = self._p(e)
        res = self.resources.setdefault(p["resource_id"], _skeleton_resource(p["resource_id"]))
        res["status"] = "blocked"
        res["availability"] = "blocked"
        res["timeline"].append(_at(e, f"冻结：{p['reason']}"))

    def _on_resource_cleared(self, e: dict) -> None:
        p = self._p(e)
        res = self.resources[p["resource_id"]]
        res["status"] = "available"
        res["holds"] = []
        res["timeline"].append(_at(e, f"解除冻结：{p['reason']}"))

    def _on_resource_recalled(self, e: dict) -> None:
        p = self._p(e)
        res = self.resources.setdefault(p["resource_id"], _skeleton_resource(p["resource_id"]))
        res["timeline"].append(_at(e, f"召回：{p['reason']}"))

    def _on_resource_returned(self, e: dict) -> None:
        p = self._p(e)
        rid = p.get("resource_id", e["aggregate_id"])
        res = self.resources.setdefault(rid, _skeleton_resource(rid))
        res["availability"] = "pending_inspection"
        res["status"] = "returned_pending"
        res["session_id"] = None
        res.setdefault("returns", []).append(
            {"kind": p["return_kind"], "from_session_id": p["from_session_id"],
             "event_id": e["event_id"], "reported_via": e["event_type"]})
        res["timeline"].append(_at(e, f"归还（{p['return_kind']}），待检查"))

    # 离线归还事件（_offline_return）与现场归还走同一状态转移；
    # 幂等已在入流时按 dedupe_key 保证。

    def _on_return_inspected(self, e: dict) -> None:
        p = self._p(e)
        res = self.resources.setdefault(p["resource_id"], _skeleton_resource(p["resource_id"]))
        res.setdefault("inspections", []).append(
            {"result": p["result"], "event_id": e["event_id"],
             "notes": p.get("notes", "")})
        if p["result"] == "pass":
            res["availability"] = "reusable"
            res["status"] = "available"
            res["location_venue_id"] = res.get("home_venue_id")
        else:
            res["availability"] = "blocked"
            res["status"] = "blocked"
        res["timeline"].append(_at(e, f"归还检查：{p['result']}"))

    # 借调申请
    def _on_loan_requested(self, e: dict) -> None:
        p = self._p(e)
        self.loans[p["loan_id"]] = {"loan_id": p["loan_id"], "status": "requested", **p}

    def _on_loan_approved(self, e: dict) -> None:
        p = self._p(e)
        loan = self.loans.setdefault(p["loan_id"], {"loan_id": p["loan_id"]})
        loan.update(status="approved", conditions=p["conditions"],
                    resource_id=p["resource_id"], session_id=p["session_id"])

    def _on_loan_rejected(self, e: dict) -> None:
        p = self._p(e)
        loan = self.loans.setdefault(p["loan_id"], {"loan_id": p["loan_id"]})
        loan.update(status="rejected", reasons=p["reasons"],
                    resource_id=p["resource_id"], session_id=p["session_id"])

    # 运输交接
    def _on_transfer_dispatched(self, e: dict) -> None:
        p = self._p(e)
        tid = p.get("transfer_id", e["aggregate_id"])
        self.transfers[tid] = {
            "transfer_id": tid, "resource_ids": list(p["resource_ids"]),
            "from_venue_id": p["from_venue_id"], "to_venue_id": p["to_venue_id"],
            "planned_arrival": p["planned_arrival"], "vehicle_id": p["vehicle_id"],
            "session_id": p.get("session_id"),
            "planned_departure": p.get("planned_departure"),
            "status": "dispatched", "handovers": [], "delay_minutes": 0,
        }
        for rid in p["resource_ids"]:
            res = self.resources.setdefault(rid, _skeleton_resource(rid))
            res["availability"] = "in_transit"
            res["transfer_id"] = tid
            res["timeline"].append(_at(e, f"装车发运 → {p['to_venue_id']}"))

    def _on_transfer_delayed(self, e: dict) -> None:
        p = self._p(e)
        order = self.transfers[p["transfer_id"]]
        order["status"] = "delayed"
        order["delay_minutes"] += int(p["delay_minutes"])
        order["latest_eta"] = p.get("new_eta")
        order.setdefault("delay_reasons", []).append(p["reason"])
        for rid in order["resource_ids"]:
            self.resources.setdefault(rid, _skeleton_resource(rid))["timeline"].append(
                _at(e, f"运输迟延 {p['delay_minutes']} 分钟：{p['reason']}"))

    def _on_transfer_handover(self, e: dict) -> None:
        p = self._p(e)
        order = self.transfers.setdefault(p["transfer_id"],
                                          {"transfer_id": p["transfer_id"], "handovers": []})
        order["handovers"].append({
            "stage": p["stage"], "resource_ids": list(p["resource_ids"]),
            "from_party": p["from_party"], "to_party": p["to_party"],
            "condition_check_passed": p["condition_check_passed"],
            "at": p.get("at", e["occurred_at"]), "event_id": e["event_id"],
            "notes": p.get("notes", ""),
        })

    def _on_transfer_completed(self, e: dict) -> None:
        p = self._p(e)
        order = self.transfers[p["transfer_id"]]
        order["status"] = "completed"
        order["arrived_at"] = p["arrived_at"]
        for rid in p.get("resource_ids", order["resource_ids"]):
            res = self.resources.setdefault(rid, _skeleton_resource(rid))
            res["availability"] = "arrived"
            res["location_venue_id"] = order["to_venue_id"]
            res["timeline"].append(_at(e, f"送达 {order['to_venue_id']}，交接完成"))

    def _on_transfer_cancelled(self, e: dict) -> None:
        p = self._p(e)
        order = self.transfers[p["transfer_id"]]
        order["status"] = "cancelled"
        for rid in p.get("resource_ids", order["resource_ids"]):
            res = self.resources.setdefault(rid, _skeleton_resource(rid))
            if res.get("availability") == "in_transit":
                res["availability"] = "at_home"
            res["timeline"].append(_at(e, f"运输取消：{p['reason']}"))

    # 场地与环境
    def _on_venue_registered(self, e: dict) -> None:
        p = self._p(e)
        vid = p.get("venue_id", e["aggregate_id"])
        self.venues[vid] = {
            "venue_id": vid, "name": p["name"],
            "accessible_entrance": p["accessible_entrance"],
            "env_capable_for_textile": p.get("env_capable_for_textile", False),
            "playback_ready": p.get("playback_ready", False),
            "status": "open", "readings": [], "latest_breach": False,
        }

    def _on_venue_taken_out_of_service(self, e: dict) -> None:
        p = self._p(e)
        venue = self.venues[p["venue_id"]]
        venue["status"] = "out_of_service"
        venue["oos_from"] = p["from_time"]
        venue["oos_to"] = p.get("to_time")
        venue["oos_reason"] = p["reason"]

    def _on_venue_resumed(self, e: dict) -> None:
        p = self._p(e)
        venue = self.venues[p["venue_id"]]
        venue["status"] = "open"
        venue["resumed_at"] = p["resumed_at"]

    def _on_environment_reading_recorded(self, e: dict) -> None:
        p = self._p(e)
        venue = self.venues[p["venue_id"]]
        reading = {"observed_at": p["observed_at"], "temp_c": p["temp_c"],
                   "humidity_pct": p["humidity_pct"], "breach": p["breach"],
                   "event_id": e["event_id"]}
        venue["readings"].append(reading)
        venue["latest_breach"] = bool(p["breach"])

    # 容量
    def _on_venue_capacity_defined(self, e: dict) -> None:
        p = self._p(e)
        self.slots[p["slot_id"]] = {
            "slot_id": p["slot_id"], "venue_id": p["venue_id"],
            "session_id": p["session_id"],
            "seats_by_pool": dict(p["seats_by_pool"]),
            "assigned_by_pool": defaultdict(int),
        }

    def _on_capacity_allocated(self, e: dict) -> None:
        p = self._p(e)
        slot = self.slots[p["slot_id"]]
        slot["assigned_by_pool"][p["pool"]] += int(p["seats"])

    def _on_capacity_released(self, e: dict) -> None:
        p = self._p(e)
        slot = self.slots[p["slot_id"]]
        slot["assigned_by_pool"][p["pool"]] -= int(p["seats"])

    def _on_quota_transferred(self, e: dict) -> None:
        p = self._p(e)
        # 名额只随替代场次迁移且按池迁移，不做跨池平均。
        for move in p["pools"]:
            src = self._slot_of(p["from_session_id"])
            dst = self._slot_of(p["to_session_id"])
            src["assigned_by_pool"][move["pool"]] -= int(move["seats"])
            dst["assigned_by_pool"][move["pool"]] += int(move["seats"])

    # 版本化内容
    def _on_exhibit_version_published(self, e: dict) -> None:
        self._publish_version(e, kind="exhibit")

    def _on_exhibit_version_withdrawn(self, e: dict) -> None:
        p = self._p(e)
        self.versions[p["version_id"]]["status"] = "withdrawn"

    def _on_material_version_published(self, e: dict) -> None:
        self._publish_version(e, kind="material")

    def _on_interpretation_version_published(self, e: dict) -> None:
        self._publish_version(e, kind="interpretation")

    def _publish_version(self, e: dict, *, kind: str) -> None:
        p = self._p(e)
        self.versions[p["version_id"]] = {
            "version_id": p["version_id"], "kind": kind,
            "course_id": p.get("course_id"), "title": p["title"],
            "excerpt": p.get("excerpt", ""), "published_at": e["occurred_at"],
            "event_id": e["event_id"], "status": "published",
        }

    # 场次
    def _on_session_opened(self, e: dict) -> None:
        p = self._p(e)
        sid = p.get("session_id", e["aggregate_id"])
        self.sessions[sid] = {
            "session_id": sid, "course_id": p["course_id"], "title": p["title"],
            "venue_id": p["venue_id"], "planned_start": p["planned_start"],
            "planned_end": p["planned_end"], "status": "open",
            "resources": {}, "instructor_id": None, "slot_id": None,
            "content": {}, "replans": [], "anomaly_event_ids": [],
            "replaces": None, "replaced_by": None,
        }

    def _on_session_content_locked(self, e: dict) -> None:
        p = self._p(e)
        sid = p.get("session_id", e["aggregate_id"])
        sess = self.sessions.setdefault(sid, _skeleton_session(sid))
        # 定版后即使材料/讲解发布新版本，本场次仍指向当时锁定的版本号。
        sess["content"] = {
            "interpretation_version_id": p["interpretation_version_id"],
            "material_version_id": p["material_version_id"],
            "exhibit_version_id": p["exhibit_version_id"],
            "locked_at": e["occurred_at"], "event_id": e["event_id"],
        }

    def _on_session_replacement_created(self, e: dict) -> None:
        p = self._p(e)
        new_sid = p.get("session_id", e["aggregate_id"])
        old_sid = p["replaces_session_id"]
        self.sessions[new_sid] = {
            **_skeleton_session(new_sid),
            "venue_id": p["venue_id"], "planned_start": p["planned_start"],
            "planned_end": p["planned_end"], "replaces": old_sid,
            "status": "replacement_open", "title": self.sessions.get(old_sid, {}).get("title"),
            "course_id": self.sessions.get(old_sid, {}).get("course_id"),
        }
        old = self.sessions.setdefault(old_sid, _skeleton_session(old_sid))
        old["replaced_by"] = new_sid

    def _on_session_rescheduled(self, e: dict) -> None:
        p = self._p(e)
        sid = p.get("session_id", e["aggregate_id"])
        sess = self.sessions.setdefault(sid, _skeleton_session(sid))
        sess["planned_start"] = p["new_start"]
        sess["planned_end"] = p.get("new_end", sess.get("planned_end"))
        sess.setdefault("reschedules", []).append(
            {"old_start": p["old_start"], "new_start": p["new_start"],
             "reason": p["reason"], "event_id": e["event_id"]})

    def _on_session_resources_replanned(self, e: dict) -> None:
        p = self._p(e)
        sid = p.get("session_id", e["aggregate_id"])
        sess = self.sessions.setdefault(sid, _skeleton_session(sid))
        released, reassigned = p.get("released", []), p.get("reassigned", [])
        for rid in released:
            sess["resources"].pop(rid, None)
            res = self.resources.setdefault(rid, _skeleton_resource(rid))
            if res.get("session_id") == sid:
                res["session_id"] = None
        for item in reassigned:
            rid = item["resource_id"]
            sess["resources"][rid] = item.get("resource_kind", "unknown")
            sess.setdefault("resource_history", {})[rid] = item.get("resource_kind", "unknown")
            self.resources.setdefault(rid, _skeleton_resource(rid))["session_id"] = sid
        sess["replans"].append({
            "trigger_event_id": p["trigger_event_id"],
            "released": list(released), "reassigned": list(reassigned),
            "event_id": e["event_id"], "at": e["occurred_at"],
        })
        sess["anomaly_event_ids"].append(p["trigger_event_id"])

    def _on_session_cancelled(self, e: dict) -> None:
        p = self._p(e)
        sid = p.get("session_id", e["aggregate_id"])
        self.sessions.setdefault(sid, _skeleton_session(sid))["status"] = "cancelled"

    def _on_session_delivered(self, e: dict) -> None:
        p = self._p(e)
        sid = p.get("session_id", e["aggregate_id"])
        sess = self.sessions.setdefault(sid, _skeleton_session(sid))
        sess["status"] = "delivered"
        sess["delivered_at"] = p["delivered_at"]
        sess["actual_venue_id"] = p["actual_venue_id"]

    # 预约与候补
    def _on_group_booking_requested(self, e: dict) -> None:
        p = self._p(e)
        self.bookings[p["booking_id"]] = {
            "booking_id": p["booking_id"], "session_id": p["session_id"],
            "group_name": p["group_name"], "seats_by_pool": dict(p["seats_by_pool"]),
            "entitlements": p.get("entitlements", []), "status": "requested",
        }

    def _on_group_booking_accepted(self, e: dict) -> None:
        p = self._p(e)
        booking = self.bookings.setdefault(p["booking_id"], {"booking_id": p["booking_id"]})
        booking.update(status="accepted", session_id=p["session_id"],
                       seats_by_pool=dict(p["seats_by_pool"]))

    def _on_group_booking_rejected(self, e: dict) -> None:
        p = self._p(e)
        booking = self.bookings.setdefault(p["booking_id"], {"booking_id": p["booking_id"]})
        booking.update(status="rejected", reasons=p["reasons"],
                       session_id=p["session_id"])

    def _on_waitlist_entry_created(self, e: dict) -> None:
        p = self._p(e)
        self.waitlists[p["waitlist_id"]] = {
            "waitlist_id": p["waitlist_id"], "session_id": p["session_id"],
            "visitor_name": p["visitor_name"], "pool": p["pool"],
            "seats": int(p["seats"]), "status": "waiting",
            "created_seq": len(self.waitlists),
        }

    def _on_waitlist_promoted(self, e: dict) -> None:
        p = self._p(e)
        entry = self.waitlists[p["waitlist_id"]]
        entry["status"] = "promoted"

    def _on_waitlist_expired(self, e: dict) -> None:
        p = self._p(e)
        self.waitlists[p["waitlist_id"]]["status"] = "expired"

    # 讲师
    def _on_instructor_registered(self, e: dict) -> None:
        p = self._p(e)
        self.instructors[p["instructor_id"]] = {
            "instructor_id": p["instructor_id"], "name": p["name"],
            "qualifications": list(p["qualifications"]),
            "assignments": {},
        }

    def _on_instructor_qualification_recorded(self, e: dict) -> None:
        p = self._p(e)
        self.instructors[p["instructor_id"]]["qualifications"] = list(p["qualifications"])

    def _on_instructor_assigned(self, e: dict) -> None:
        p = self._p(e)
        inst = self.instructors.setdefault(p["instructor_id"],
                                           {"instructor_id": p["instructor_id"],
                                            "qualifications": [], "assignments": {}})
        inst["assignments"][p["session_id"]] = {
            "qualification_version": p["qualification_version"],
            "event_id": e["event_id"],
        }
        sess = self.sessions.setdefault(p["session_id"], _skeleton_session(p["session_id"]))
        sess["instructor_id"] = p["instructor_id"]
        sess["instructor_qualification_version"] = p["qualification_version"]

    def _on_instructor_unassigned(self, e: dict) -> None:
        p = self._p(e)
        self.instructors[p["instructor_id"]]["assignments"].pop(p["session_id"], None)
        sess = self.sessions.get(p["session_id"])
        if sess and sess.get("instructor_id") == p["instructor_id"]:
            sess["instructor_id"] = None

    # 离线补报（三事件的业务状态；只认一次已在入流时保证）
    def _on_offline_report_started(self, e: dict) -> None:
        self._record_offline(e, "started")

    def _on_offline_report_completed(self, e: dict) -> None:
        self._record_offline(e, "completed")

    def _offline_return(self, e: dict) -> None:
        p = self._p(e)
        # 离线补报的归还与 RESOURCE_RETURNED 等效：资源进入待检查。
        for rid in p["resource_ids"]:
            res = self.resources.setdefault(rid, _skeleton_resource(rid))
            res["availability"] = "pending_inspection"
            res["status"] = "returned_pending"
            res["session_id"] = None
            res.setdefault("returns", []).append(
                {"kind": "offline_backfill", "from_session_id": p["session_id"],
                 "event_id": e["event_id"], "reported_via": e["event_type"]})
            res["timeline"].append(_at(e, "离线补报归还，待检查"))
        self._record_offline(e, "returned")

    def _record_offline(self, e: dict, stage: str) -> None:
        p = self._p(e)
        self.offline_reports.append({
            "stage": stage, "branch_id": p["branch_id"],
            "dedupe_key": e["dedupe_key"], "business_time": p.get("business_time"),
            "event_id": e["event_id"], "accepted_at": e["occurred_at"],
        })

    def _on_feedback_submitted(self, e: dict) -> None:
        p = self._p(e)
        self.feedback.append({
            "feedback_id": p["feedback_id"], "session_id": p["session_id"],
            "author_role": p["author_role"], "rating": p["rating"],
            "comment": p.get("comment", ""), "event_id": e["event_id"],
        })

    # -- 查询投影 -----------------------------------------------------------

    def _slot_of(self, session_id: str) -> dict:
        for slot in self.slots.values():
            if slot["session_id"] == session_id:
                return slot
        raise KeyError(f"场次 {session_id} 没有容量档期")

    def session_view(self, session_id: str) -> dict:
        """从一场活动还原：物品、人员、场地、定版内容、交接、异常与反馈。"""
        sess = self.sessions[session_id]
        venue = self.venues.get(sess.get("actual_venue_id") or sess["venue_id"], {})
        resources = []
        history = sess.get("resource_history", sess["resources"])
        for rid, kind in history.items():
            res = self.resources.get(rid, {})
            resources.append({
                "resource_id": rid, "resource_kind": kind, "title": res.get("title"),
                "status": res.get("status"), "availability": res.get("availability"),
                "location_venue_id": res.get("location_venue_id"),
                "transfer_id": res.get("transfer_id"),
                "in_final_plan": rid in sess["resources"],
            })
        instructor = None
        if sess.get("instructor_id"):
            inst = self.instructors[sess["instructor_id"]]
            instructor = {
                "instructor_id": sess["instructor_id"], "name": inst["name"],
                "qualification_version": sess.get("instructor_qualification_version"),
                "qualifications": inst["qualifications"],
            }
        content = {}
        for key, vid in sess.get("content", {}).items():
            if key.endswith("_id"):
                ver = self.versions.get(vid)
                content[key] = vid
                content[key.replace("_version_id", "_snapshot")] = (
                    {"title": ver["title"], "excerpt": ver["excerpt"],
                     "published_at": ver["published_at"]} if ver else None)
        transfers = self._session_transfers(session_id)
        return {
            "session_id": session_id,
            "title": sess.get("title"), "course_id": sess.get("course_id"),
            "status": sess["status"],
            "planned_venue_id": sess["venue_id"],
            "venue": {"venue_id": venue.get("venue_id"), "name": venue.get("name"),
                      "status": venue.get("status"),
                      "accessible_entrance": venue.get("accessible_entrance")},
            "actual_venue_id": sess.get("actual_venue_id"),
            "planned_start": sess["planned_start"], "planned_end": sess["planned_end"],
            "resources": resources,
            "instructor": instructor,
            "content_lock": content,
            "transfers": transfers,
            "handovers": [h for t in transfers for h in t["handovers"]],
            "anomalies": self._session_anomalies(session_id),
            "replans": sess.get("replans", []),
            "replaces": sess.get("replaces"),
            "replaced_by": sess.get("replaced_by"),
            "feedback": [f for f in self.feedback if f["session_id"] == session_id],
        }

    def _session_transfers(self, session_id: str) -> list[dict]:
        sess = self.sessions[session_id]
        rids = set(sess.get("resource_history", sess["resources"]))
        out = []
        for order in self.transfers.values():
            if order.get("session_id") == session_id or rids & set(order["resource_ids"]):
                out.append(order)
        return out

    def _session_anomalies(self, session_id: str) -> list[dict]:
        """把触发本场重排的事件、运输迟延、环境超标、场馆停用汇成可追溯清单。"""
        by_id = {e["event_id"]: e for e in self.events}
        anomalies: list[dict] = []
        for trigger_id in self.sessions[session_id].get("anomaly_event_ids", []):
            e = by_id.get(trigger_id)
            if e:
                anomalies.append({"event_id": trigger_id, "event_type": e["event_type"],
                                  "summary": e["summary"], "payload": e["payload"]})
        for order in self._session_transfers(session_id):
            if order["status"] in ("delayed", "cancelled"):
                anomalies.append({"kind": "transfer", "transfer_id": order["transfer_id"],
                                  "status": order["status"],
                                  "delay_minutes": order.get("delay_minutes", 0)})
        venue_id = self.sessions[session_id]["venue_id"]
        venue = self.venues.get(venue_id, {})
        if venue.get("status") == "out_of_service":
            anomalies.append({"kind": "venue_out_of_service", "venue_id": venue_id,
                              "reason": venue.get("oos_reason")})
        for reading in venue.get("readings", []):
            if reading["breach"]:
                anomalies.append({"kind": "environment_breach", **reading})
        return anomalies

    def booking_page(self, session_id: str) -> dict:
        """带队老师预约页实际看到的信息：地点、教具到达、条件、剩余名额。"""
        sess = self.sessions[session_id]
        venue = self.venues[sess["venue_id"]]
        slot = self._slot_of(session_id)

        resource_lines = []
        history = sess.get("resource_history", sess["resources"])
        for rid, kind in history.items():
            res = self.resources.get(rid, {})
            in_plan = rid in sess["resources"]
            if kind == "digital":
                # 数字内容没有实物运输：授权覆盖本场即视为就绪。
                licensed = any(
                    loan.get("resource_id") == rid
                    and loan.get("session_id") == session_id
                    and loan.get("status") == "approved"
                    for loan in self.loans.values())
                arrived = licensed and res.get("status") != "blocked"
                label = "授权就绪" if arrived else "授权未就绪"
            else:
                arrived = (
                    in_plan
                    and res.get("location_venue_id") == sess["venue_id"]
                    and res.get("availability") in ("arrived", "reusable", "at_home")
                )
                label = {"in_transit": "在途中", "arrived": "已到馆",
                         "reusable": "已到馆", "at_home": "本馆常备",
                         "blocked": "冻结中",
                         "pending_inspection": "待检查"}.get(
                    res.get("availability"), res.get("availability"))
                if not in_plan:
                    label = f"本场不使用（{label}）"
            resource_lines.append({
                "resource_id": rid, "resource_kind": kind, "title": res.get("title"),
                "arrived": arrived, "arrival_status": label,
                "in_final_plan": in_plan,
            })

        remaining = {pool: int(slot["seats_by_pool"].get(pool, 0))
                           - int(slot["assigned_by_pool"].get(pool, 0))
                     for pool in slot["seats_by_pool"]}

        conditions = []
        if any(k == "original" for k in sess["resources"].values()):
            conditions.append(
                "真品展出需现场温湿度达标"
                + ("（当前达标）" if not venue.get("latest_breach") else "（当前超标，真品已撤出）"))
        if venue.get("accessible_entrance"):
            conditions.append("有无障碍通道")
        if sess.get("replaces"):
            conditions.append(f"本场为 {sess['replaces']} 临时闭馆后的替代场次")

        return {
            "session_id": session_id, "title": sess.get("title"),
            "venue_id": venue["venue_id"], "venue_name": venue["name"],
            "venue_status": venue["status"],
            "accessible_entrance": venue["accessible_entrance"],
            "planned_start": sess["planned_start"], "planned_end": sess["planned_end"],
            "session_status": sess["status"],
            "teaching_aids": resource_lines,
            "remaining_seats_by_pool": remaining,
            "mobility_access_remaining": remaining.get("mobility_access", 0),
            "conditions": conditions,
            "replaces_session_id": sess.get("replaces"),
        }

    def headquarters_board(self) -> dict:
        """总馆台账：在途中 / 待检查 / 可再次使用，其余单列。"""
        board = {"in_transit": [], "pending_inspection": [], "reusable": [], "other": []}
        reusable_states = {"reusable", "at_home"}
        for rid, res in self.resources.items():
            line = {"resource_id": rid, "resource_kind": res.get("resource_kind"),
                    "title": res.get("title"), "location_venue_id": res.get("location_venue_id")}
            avail = res.get("availability")
            if avail == "in_transit":
                bucket = "in_transit"
            elif avail == "pending_inspection":
                bucket = "pending_inspection"
            elif avail in reusable_states and res.get("status") != "blocked":
                bucket = "reusable"
            else:
                bucket = "other"
            board[bucket].append(line)
        return board

    def resource_trace(self, resource_id: str) -> list[dict]:
        return list(self.resources[resource_id]["timeline"])


# --- 小工具 ------------------------------------------------------------------

_OFFLINE = {"OFFLINE_REPORT_STARTED", "OFFLINE_REPORT_COMPLETED",
            "OFFLINE_RETURN_REPORTED"}


def _at(event: dict, note: str) -> dict:
    return {"at": event["occurred_at"], "event_id": event["event_id"],
            "event_type": event["event_type"], "note": note}


def _skeleton_resource(rid: str) -> dict:
    return {"resource_id": rid, "resource_kind": "unknown", "title": None,
            "home_venue_id": None, "status": "available", "holds": [],
            "location_venue_id": None, "session_id": None,
            "availability": "unknown", "timeline": []}


def _skeleton_session(sid: str) -> dict:
    return {"session_id": sid, "title": None, "course_id": None,
            "venue_id": None, "planned_start": None, "planned_end": None,
            "status": "open", "resources": {}, "resource_history": {},
            "instructor_id": None,
            "slot_id": None, "content": {}, "replans": [],
            "anomaly_event_ids": [], "replaces": None, "replaced_by": None}


# 离线归还处理器在类定义后补绑（语义见 _offline_return）。
Replay._on_offline_return_reported = Replay._offline_return  # type: ignore[attr-defined]


def replay(events: list[dict], *, strict: bool = True,
           as_of: str | None = None) -> Replay:
    return Replay(events, strict=strict, as_of=as_of)
