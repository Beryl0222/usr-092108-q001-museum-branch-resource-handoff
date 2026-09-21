import json
import unittest
from pathlib import Path

from src.catalog import (AGGREGATE_TYPES, EVENT_TYPES, OFFLINE_EVENTS,
                         aggregates_for, required_payload)
from src.validator import validate_event, validate_event_full

ROOT = Path(__file__).parents[1]


def _scenario():
    return json.loads((ROOT / "data" / "scenario_northern_wei.json").read_text("utf-8"))


class ContractTest(unittest.TestCase):
    def test_sample_matches_envelope(self) -> None:
        sample = json.loads((ROOT / "data" / "sample.json").read_text("utf-8"))
        self.assertEqual(validate_event(sample), [])
        # 遗留聚合 collection_resource 仍被完整校验接受。
        self.assertEqual(validate_event_full(sample), [])

    def test_basic_envelope_rejects_missing_fields(self) -> None:
        errors = validate_event({"event_id": "x"})
        self.assertTrue(any("event_type" in e for e in errors))

    def test_basic_envelope_rejects_bad_version(self) -> None:
        base = dict(event_id="e1", event_type="SESSION_OPENED",
                    aggregate_type="activity_session", aggregate_id="s1",
                    occurred_at="2026-09-20T10:00:00+08:00", version=1, summary="x")
        self.assertTrue(validate_event({**base, "version": 0}))
        self.assertTrue(validate_event({**base, "version": True}))  # bool 不算整数

    def test_unknown_event_and_aggregate_rejected(self) -> None:
        rec = _envelope("NO_SUCH_EVENT", "activity_session")
        errors = validate_event_full(rec)
        self.assertTrue(any("未知事件类型" in e for e in errors))
        rec = _envelope("SESSION_OPENED", "no_such_aggregate")
        self.assertTrue(any("未知聚合类型" in e for e in validate_event_full(rec)))

    def test_event_aggregate_pairing(self) -> None:
        # 借调申请只能落在 loan_request 上，不能落在场地。
        rec = _envelope("LOAN_REQUESTED", "venue")
        self.assertTrue(any("不能落在聚合" in e for e in validate_event_full(rec)))
        rec = _envelope("LOAN_REQUESTED", "loan_request",
                        {"loan_id": "l1", "resource_id": "r1", "resource_kind": "replica",
                         "session_id": "s1", "requested_by": "v1"})
        self.assertEqual(validate_event_full(rec), [])

    def test_payload_required_fields(self) -> None:
        rec = _envelope("VENUE_REGISTERED", "venue", {"venue_id": "v1"})  # 缺字段
        errors = validate_event_full(rec)
        self.assertIn("payload 缺少必填字段：name", errors)
        self.assertIn("payload 缺少必填字段：accessible_entrance", errors)

    def test_offline_event_requires_dedupe_key(self) -> None:
        for etype in OFFLINE_EVENTS:
            rec = _envelope(etype, "activity_session",
                            {"branch_id": "v1", "report_scope": "x",
                             "business_time": "2026-09-27T16:00:00+08:00"})
            self.assertTrue(any("dedupe_key" in e for e in validate_event_full(rec)), etype)

    def test_catalog_covers_fourteen_stable_identities(self) -> None:
        expected = {
            "collection_object", "replica", "digital_content", "exhibit_version",
            "venue", "venue_slot", "instructor", "course_material", "group_booking",
            "waitlist_entry", "transfer_order", "activity_session",
            "activity_feedback", "loan_request",
        }
        self.assertTrue(expected <= set(AGGREGATE_TYPES))

    def test_every_event_type_has_spec(self) -> None:
        for etype in EVENT_TYPES:
            self.assertTrue(aggregates_for(etype))
            self.assertIsInstance(required_payload(etype), tuple)

    def test_scenario_events_all_valid(self) -> None:
        for event in _scenario():
            self.assertEqual(validate_event_full(event), [], event["event_id"])

    def test_generated_schema_matches_catalog(self) -> None:
        schema = json.loads((ROOT / "contracts" / "domain.schema.json").read_text("utf-8"))
        self.assertEqual(set(schema["properties"]["event_type"]["enum"]), set(EVENT_TYPES))
        self.assertEqual(set(schema["properties"]["aggregate_type"]["enum"]),
                         set(AGGREGATE_TYPES))


def _envelope(event_type: str, aggregate_type: str, payload=None) -> dict:
    return {
        "event_id": f"test-{event_type}",
        "event_type": event_type,
        "aggregate_type": aggregate_type,
        "aggregate_id": "test-agg",
        "occurred_at": "2026-09-20T10:00:00+08:00",
        "version": 1,
        "summary": "测试事件",
        "payload": payload if payload is not None else {},
    }


if __name__ == "__main__":
    unittest.main()
