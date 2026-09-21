import json
import unittest
from pathlib import Path

from src.validator import validate_event, validate_stream, deduplicate

ROOT = Path(__file__).parents[1]


def load_sample() -> dict:
    return json.loads((ROOT / "data" / "sample.json").read_text(encoding="utf-8"))


class ContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = load_sample()
        self.events = self.doc["events"]

    def test_every_event_matches_envelope(self) -> None:
        for e in self.events:
            self.assertEqual(validate_event(e), [], f"{e['event_id']} 信封不合规")

    def test_sample_stream_is_consistent(self) -> None:
        self.assertEqual(validate_stream(self.events), [])

    def test_event_ids_and_versions(self) -> None:
        self.assertEqual(len({e["event_id"] for e in self.events}), len(self.events))
        per_agg: dict[str, list[int]] = {}
        for e in self.events:
            per_agg.setdefault(e["aggregate_id"], []).append(e["version"])
        for agg, versions in per_agg.items():
            self.assertEqual(versions, list(range(1, len(versions) + 1)), agg)

    def test_duplicate_deliveries_are_rejected_once(self) -> None:
        # 含重复投递的原始输入：去重后只接收首条
        accepted, rejected = deduplicate(self.events + self.doc["duplicate_deliveries"])
        self.assertEqual(len(accepted), len(self.events))
        self.assertEqual(len(rejected), len(self.doc["duplicate_deliveries"]))
        # 流校验也必须把重复幂等键标出来
        errors = validate_stream(self.events + self.doc["duplicate_deliveries"])
        self.assertTrue(any("idempotency_key 重复" in m for m in errors))

    def test_causal_references_resolve(self) -> None:
        ids = {e["event_id"] for e in self.events}
        for e in self.events:
            cause = e.get("caused_by_event_id")
            if cause:
                self.assertIn(cause, ids, f"{e['event_id']} 的因果引用悬空")

    def test_schema_file_matches_validator_enums(self) -> None:
        schema = json.loads((ROOT / "contracts" / "domain.schema.json").read_text(encoding="utf-8"))
        from src import validator as v
        self.assertEqual(set(schema["properties"]["event_type"]["enum"]), v.EVENT_TYPES)
        self.assertEqual(set(schema["properties"]["aggregate_type"]["enum"]), v.AGGREGATE_TYPES)
        for name in ("event_id", "event_type", "aggregate_type", "aggregate_id",
                     "occurred_at", "version", "summary"):
            self.assertIn(name, schema["required"])

    def test_schema_validates_with_jsonschema_if_available(self) -> None:
        try:
            import jsonschema  # type: ignore
        except ImportError:
            self.skipTest("环境未安装 jsonschema，跳过深度 schema 校验")
        schema = json.loads((ROOT / "contracts" / "domain.schema.json").read_text(encoding="utf-8"))
        for e in self.events:
            jsonschema.validate(e, schema)


if __name__ == "__main__":
    unittest.main()
