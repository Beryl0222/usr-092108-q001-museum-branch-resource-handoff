"""校验领域事件信封的基础字段与事件目录一致性。

- ``validate_event``：只校验七个基础字段（保持仓库早期约定，旧调用方不变）。
- ``validate_event_full``：在基础字段之上，按 ``catalog`` 校验事件类型、
  聚合类型是否合法、该事件能否落在该聚合上、payload 必填项是否齐全，
  以及离线补报事件是否携带 dedupe_key。
"""

from datetime import datetime

from . import catalog

REQUIRED = ("event_id", "event_type", "aggregate_type", "aggregate_id",
            "occurred_at", "version", "summary")


def validate_event(record: dict) -> list[str]:
    errors = [f"缺少字段：{name}" for name in REQUIRED if name not in record]
    if "version" in record and (not isinstance(record["version"], int)
                                or isinstance(record["version"], bool)
                                or record["version"] < 1):
        errors.append("version 必须是正整数")
    return errors


def _valid_datetime(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def validate_event_full(record: dict) -> list[str]:
    errors = validate_event(record)

    event_type = record.get("event_type")
    aggregate_type = record.get("aggregate_type")

    if event_type not in catalog.EVENT_TYPES:
        # 不在新目录里、也没有显式定义的类型直接拒绝（遗留事件名已在目录中保留）。
        errors.append(f"未知事件类型：{event_type}")
    if aggregate_type not in catalog.AGGREGATE_TYPES:
        errors.append(f"未知聚合类型：{aggregate_type}")

    if event_type in catalog.EVENT_TYPES and aggregate_type in catalog.AGGREGATE_TYPES:
        if aggregate_type not in catalog.aggregates_for(event_type):
            errors.append(
                f"事件 {event_type} 不能落在聚合 {aggregate_type} 上，"
                f"允许：{'、'.join(catalog.aggregates_for(event_type))}")

    if not _valid_datetime(record.get("occurred_at", "")):
        errors.append("occurred_at 必须是 ISO 8601 日期时间")

    payload = record.get("payload")
    if payload is not None:
        if not isinstance(payload, dict):
            errors.append("payload 必须是对象")
        elif event_type in catalog.EVENT_TYPES:
            for key in catalog.required_payload(event_type):
                if key not in payload:
                    errors.append(f"payload 缺少必填字段：{key}")

    # 离线补报（开始/完成/归还）依赖 dedupe_key 保证“只认一次”。
    if event_type in catalog.OFFLINE_EVENTS:
        if not isinstance(record.get("dedupe_key"), str) or not record.get("dedupe_key"):
            errors.append(f"{event_type} 必须携带非空 dedupe_key")

    return errors
