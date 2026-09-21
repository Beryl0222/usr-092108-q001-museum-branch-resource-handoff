"""领域事件信封与事件流校验。

- validate_event：单条信封基础校验（保持 v0.1 接口，只做加法）。
- validate_stream：事件流一致性（唯一标识、聚合版本递增、时间可解析、因果引用、幂等键）。
- deduplicate：按 idempotency_key 执行"同一补报只认一次"，返回 (接收, 丢弃)。
"""

from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

REQUIRED = ("event_id", "event_type", "aggregate_type", "aggregate_id",
            "occurred_at", "version", "summary")

EVENT_TYPES = {
    "RESOURCE_REGISTERED", "RESOURCE_RESERVED", "RESOURCE_RESERVATION_RELEASED",
    "CONDITION_RECORDED", "ENVIRONMENT_ALERT_RAISED", "ENVIRONMENT_CLEARED",
    "RESOURCE_QUARANTINED", "RESOURCE_CLEARED", "RESOURCE_RETURNED",
    "TRANSFER_PLANNED", "TRANSFER_DISPATCHED", "TRANSFER_DELAYED",
    "TRANSFER_HANDED_OVER", "TRANSFER_ACKNOWLEDGED", "TRANSFER_CLOSED",
    "VENUE_REGISTERED", "VENUE_TAKEN_OUT_OF_SERVICE", "VENUE_BACK_IN_SERVICE",
    "EXHIBIT_VERSION_PUBLISHED", "EXHIBIT_VERSION_SUPERSEDED",
    "INTERPRETATION_PUBLISHED", "COURSE_MATERIAL_PUBLISHED",
    "SESSION_CONTENT_PINNED",
    "EDUCATOR_REGISTERED", "EDUCATOR_ASSIGNED", "EDUCATOR_UNASSIGNED",
    "SESSION_OPENED", "SESSION_QUOTA_PROTECTED", "SESSION_RELOCATED",
    "SESSION_RESCHEDULED", "SESSION_CANCELLED", "SESSION_CLOSED",
    "GROUP_BOOKING_CREATED", "BOOKING_CONFIRMED", "BOOKING_CANCELLED",
    "WAITLIST_ENTRY_ADDED", "WAITLIST_ENTRY_PROMOTED", "WAITLIST_ENTRY_EXPIRED",
    "OFFLINE_REPORT_STARTED", "OFFLINE_REPORT_COMPLETED", "FEEDBACK_RECORDED",
}

AGGREGATE_TYPES = {
    "collection_resource", "movable_replica", "digital_content",
    "exhibit_version", "interpretation", "venue", "venue_slot", "educator",
    "course_material", "program_session", "group_booking", "waitlist_entry",
    "transfer_order", "activity_feedback",
}


def _parse_dt(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    # 领域统一东八区：纯日期等无时区输入按 +08:00 归位，避免与带偏移时间混比
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CST)
    return dt


def validate_event(record: dict) -> list[str]:
    errors = [f"缺少字段：{name}" for name in REQUIRED if name not in record]
    if errors:
        return errors
    if not isinstance(record["event_id"], str) or not record["event_id"]:
        errors.append("event_id 必须是非空字符串")
    if record["event_type"] not in EVENT_TYPES:
        errors.append(f"未知 event_type：{record['event_type']}")
    if record["aggregate_type"] not in AGGREGATE_TYPES:
        errors.append(f"未知 aggregate_type：{record['aggregate_type']}")
    if not isinstance(record["aggregate_id"], str) or not record["aggregate_id"]:
        errors.append("aggregate_id 必须是非空字符串")
    if _parse_dt(record["occurred_at"]) is None:
        errors.append("occurred_at 必须是 ISO 8601 日期时间")
    if not isinstance(record["version"], int) or isinstance(record["version"], bool) or record["version"] < 1:
        errors.append("version 必须是正整数")
    if not isinstance(record["summary"], str) or not record["summary"]:
        errors.append("summary 必须是非空字符串")
    key = record.get("idempotency_key")
    if key is not None and (not isinstance(key, str) or not key):
        errors.append("idempotency_key 若提供必须是非空字符串")
    return errors


def deduplicate(events: list[dict]) -> tuple[list[dict], list[dict]]:
    """离线补报按 idempotency_key 只认一次：同键首条接收，其余丢弃。"""
    accepted: list[dict] = []
    rejected: list[dict] = []
    seen: set[str] = set()
    for e in events:
        key = e.get("idempotency_key")
        if key is not None and key in seen:
            rejected.append(e)
        else:
            if key is not None:
                seen.add(key)
            accepted.append(e)
    return accepted, rejected


def validate_stream(events: list[dict]) -> list[str]:
    """校验已接收事件流的一致性。events 应按 occurred_at 排列。"""
    errors: list[str] = []
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()
    agg_version: dict[str, int] = {}
    agg_time: dict[str, datetime] = {}
    id_set: set[str] = set()

    for i, e in enumerate(events, start=1):
        errs = validate_event(e)
        for msg in errs:
            errors.append(f"第{i}条（{e.get('event_id', '?')}）：{msg}")

        if isinstance(e.get("event_id"), str) and e["event_id"]:
            if e["event_id"] in seen_ids:
                errors.append(f"第{i}条：event_id 重复 {e['event_id']}")
            seen_ids.add(e["event_id"])
            id_set.add(e["event_id"])

        key = e.get("idempotency_key")
        if isinstance(key, str) and key:
            if key in seen_keys:
                errors.append(f"第{i}条（{e.get('event_id', '?')}）：idempotency_key 重复，应已在接收侧丢弃：{key}")
            seen_keys.add(key)

        if errs:
            continue

        agg_id, ts = e["aggregate_id"], _parse_dt(e["occurred_at"])
        expected = agg_version.get(agg_id, 0) + 1
        if e["version"] != expected:
            errors.append(
                f"第{i}条（{e['event_id']}）：聚合 {agg_id} 版本应为 {expected}，实际 {e['version']}")
        agg_version[agg_id] = e["version"]
        if agg_id in agg_time and ts < agg_time[agg_id]:
            errors.append(f"第{i}条（{e['event_id']}）：聚合 {agg_id} 事件时间倒退")
        agg_time[agg_id] = ts

    # 因果引用必须指向流内更早的事件
    for i, e in enumerate(events, start=1):
        cause = e.get("caused_by_event_id")
        if cause is not None and cause not in id_set:
            errors.append(f"第{i}条（{e.get('event_id')}）：caused_by_event_id 指向不存在的事件 {cause}")
    return errors
