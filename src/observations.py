"""读取脱敏试点观察样例。"""

import json
from pathlib import Path

REQUIRED_FIELDS = {"evidence_id", "clause_id", "site", "period", "summary", "deidentified"}


def load_observations(path: str | Path) -> list[dict]:
    """返回脱敏观察记录列表;任何未脱敏或字段不全的记录都会导致失败。"""
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    observations = value.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ValueError("样例缺少观察记录")
    seen = set()
    for item in observations:
        missing = REQUIRED_FIELDS - item.keys()
        if missing:
            raise ValueError(f"观察记录缺少字段: {sorted(missing)}")
        if item["deidentified"] is not True:
            raise ValueError(f"观察样例必须脱敏: {item.get('evidence_id')}")
        if item["evidence_id"] in seen:
            raise ValueError(f"观察记录标识重复: {item['evidence_id']}")
        seen.add(item["evidence_id"])
    return observations
