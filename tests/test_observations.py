import json
import tempfile
import unittest
from pathlib import Path

from src.observations import load_observations
from src.platform import DraftingPlatform
from src.drafting import DraftingError

ROLES = ["临床科室", "伦理委员会", "科研团队", "设备企业", "受试者管理人员"]


class ObservationsTest(unittest.TestCase):
    def test_fixture_loads_and_imports_as_evidence(self):
        observations = load_observations(Path("fixtures/pilot_observations.json"))
        self.assertEqual(len(observations), 3)
        platform = DraftingPlatform(roles=ROLES)
        platform.register_actor("res-01", "赵研究员", "科研团队", "某高校脑机实验室")
        platform.add_clause("CL-5.2", "第5章 病房分区", "信号屏蔽区设置", requires_pilot=True)
        platform.add_clause("CL-6.1", "第6章 人员配置", "专职数据管理员")
        platform.add_clause("CL-7.3", "第7章 异常处置", "应急响应演练")
        imported = platform.import_observations("res-01", observations)
        self.assertEqual(imported, ["EV-2026-001", "EV-2026-002", "EV-2026-003"])
        self.assertEqual(platform.evidence["EV-2026-002"].clause_id, "CL-6.1")

    def test_rejects_identifiable_sample(self):
        sample = {
            "domain": "bci-ward-standard-drafting",
            "version": 1,
            "sample_id": "bad-sample",
            "observations": [
                {
                    "evidence_id": "EV-X",
                    "clause_id": "CL-1",
                    "site": "某病区",
                    "period": "2026-01",
                    "summary": "含可识别个人信息的记录",
                    "deidentified": False,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(sample, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "脱敏"):
                load_observations(path)

    def test_rejects_missing_fields(self):
        sample = {"observations": [{"evidence_id": "EV-Y", "clause_id": "CL-1"}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "incomplete.json"
            path.write_text(json.dumps(sample, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "缺少字段"):
                load_observations(path)

    def test_import_unknown_clause_rejected(self):
        platform = DraftingPlatform(roles=ROLES)
        platform.register_actor("res-01", "赵研究员", "科研团队", "某高校脑机实验室")
        with self.assertRaisesRegex(DraftingError, "未知条款"):
            platform.import_observations("res-01", [
                {"evidence_id": "EV-Z", "clause_id": "CL-9.9", "site": "试点病区(已脱敏)",
                 "period": "2026-01", "summary": "汇总指标", "deidentified": True}
            ])


if __name__ == "__main__":
    unittest.main()
