#!/usr/bin/env python3
"""从 src/catalog.py 生成 contracts/domain.schema.json。

事件信封（七个基础字段）保持仓库原有结构不变；
枚举值与 payload 必填项以 catalog 为单一事实源，禁止手改生成结果。
"""

import json
from pathlib import Path

from src import catalog

ROOT = Path(__file__).resolve().parents[1]


def build_schema() -> dict:
    event_types = list(catalog.EVENT_TYPES)
    aggregate_types = list(catalog.AGGREGATE_TYPES)

    # 用 oneOf(if/then) 描述“事件类型 → 允许的聚合类型 → payload 必填项”。
    branches = []
    for event_type, (aggregates, required_payload) in catalog._EVENT_SPEC.items():  # noqa: SLF001
        payload_props = {key: {"minLength": 1} for key in required_payload}
        branches.append({
            "if": {"properties": {"event_type": {"const": event_type}}},
            "then": {
                "properties": {
                    "aggregate_type": {"enum": list(aggregates)},
                    "payload": {
                        "type": "object",
                        "required": list(required_payload),
                        "properties": {
                            **payload_props,
                            # 载荷允许各分馆附带现场细节。
                        },
                        "additionalProperties": True,
                    },
                }
            },
        })

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "博物馆分馆资源接力领域事件",
        "type": "object",
        "required": ["event_id", "event_type", "aggregate_type", "aggregate_id",
                     "occurred_at", "version", "summary"],
        "properties": {
            "event_id": {"type": "string", "minLength": 1},
            "event_type": {"type": "string", "enum": event_types},
            "aggregate_type": {"type": "string", "enum": aggregate_types},
            "aggregate_id": {"type": "string", "minLength": 1},
            "occurred_at": {"type": "string", "format": "date-time"},
            "version": {"type": "integer", "minimum": 1},
            "summary": {"type": "string", "minLength": 1},
            "payload": {"type": "object", "additionalProperties": True},
            "dedupe_key": {"type": "string", "minLength": 1},
            "recorded_at": {"type": "string", "format": "date-time"},
            "causation_id": {"type": "string", "minLength": 1},
            "correlation_id": {"type": "string", "minLength": 1},
            "actor": {"type": "string", "minLength": 1},
            "source": {"type": "string", "minLength": 1},
            "branch_id": {"type": "string", "minLength": 1},
        },
        "allOf": branches,
        "additionalProperties": True,
        "description": (
            "离线补报事件 "
            + "、".join(catalog.OFFLINE_EVENTS)
            + " 必须携带非空 dedupe_key（业务层强制：同一补报只认一次）。"
        ),
    }


def main() -> None:
    target = ROOT / "contracts" / "domain.schema.json"
    target.write_text(
        json.dumps(build_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"已生成 {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
