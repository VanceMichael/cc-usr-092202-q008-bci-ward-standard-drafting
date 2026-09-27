"""脑机接口病房标准协同编制的领域模型。

保存章节条款、术语、规范性引用、提案、意见与反对、试点证据、
会议表决以及发布留档所需的全部记录类型。
流程规则(征求意见、逐条处理、送审、发布)由 `src/platform.py` 执行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

SECRETARIAT_ROLE = "秘书处"


class DraftingError(Exception):
    """违反标准编制流程规则。"""


class DraftStatus(str, Enum):
    WORKING = "working"  # 未公开工作草案
    COMMENT = "comment"  # 征求意见中
    SUBMISSION = "submission"  # 送审稿
    PUBLISHED = "published"  # 已发布
    SUPERSEDED = "superseded"  # 已被新版替代
    RETURNED = "returned"  # 表决未通过,退回修改


class CommentKind(str, Enum):
    SUGGESTION = "suggestion"  # 一般意见
    OBJECTION = "objection"  # 反对意见


class Disposition(str, Enum):
    ADOPTED = "adopted"  # 采纳
    PARTIALLY_ADOPTED = "partially_adopted"  # 部分采纳
    REJECTED = "rejected"  # 不采纳


class Ballot(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    ABSTAIN = "abstain"


class ReferenceStatus(str, Enum):
    CURRENT = "current"
    WITHDRAWN = "withdrawn"


@dataclass
class Actor:
    """参与编制的成员,角色取自共享领域资料中的协作角色。"""

    actor_id: str
    name: str
    role: str
    organization: str


@dataclass
class Clause:
    """标准章节中的一条要求;允许存在多份并行草案。"""

    clause_id: str
    chapter: str
    title: str
    requires_pilot: bool = False


@dataclass
class Term:
    term: str
    definition: str
    source: str = ""


@dataclass
class NormativeReference:
    reference_id: str
    code: str
    title: str
    status: ReferenceStatus = ReferenceStatus.CURRENT


@dataclass
class Draft:
    """条款草案。WORKING/RETURNED 状态为未公开草案,按角色限制可见。"""

    draft_id: str
    clause_id: str
    text: str
    author_id: str
    status: DraftStatus = DraftStatus.WORKING
    version: int = 1
    visible_roles: frozenset[str] = field(default_factory=frozenset)
    reference_ids: list[str] = field(default_factory=list)
    meeting_id: str | None = None
    vote_id: str | None = None
    withdrawal_flags: list[str] = field(default_factory=list)


@dataclass
class Proposal:
    proposal_id: str
    clause_id: str
    proposer_id: str
    summary: str
    rationale: str
    draft_id: str | None = None


@dataclass
class Comment:
    """征求意见阶段收到的意见;反对意见以 OBJECTION 标识。"""

    comment_id: str
    draft_id: str
    author_id: str
    kind: CommentKind
    content: str
    disposition: Disposition | None = None
    disposition_reason: str = ""
    handler_id: str | None = None

    @property
    def resolved(self) -> bool:
        return self.disposition is not None


@dataclass
class PilotEvidence:
    """试点证据,必须脱敏后方可引用。"""

    evidence_id: str
    clause_id: str
    site: str
    period: str
    summary: str
    submitted_by: str
    deidentified: bool = True


@dataclass
class Meeting:
    """编制会议。形成送审稿要求达到法定人数且利益冲突声明齐全。"""

    meeting_id: str
    held_on: date
    attendee_ids: list[str]
    quorum: int
    coi_declared: set[str] = field(default_factory=set)

    @property
    def is_quorate(self) -> bool:
        return len(set(self.attendee_ids)) >= self.quorum

    @property
    def coi_complete(self) -> bool:
        return set(self.attendee_ids) <= self.coi_declared


@dataclass
class Vote:
    vote_id: str
    meeting_id: str
    draft_id: str
    ballots: dict[str, Ballot] = field(default_factory=dict)

    def tally(self) -> dict[str, int]:
        result = {ballot.value: 0 for ballot in Ballot}
        for ballot in self.ballots.values():
            result[ballot.value] += 1
        return result


@dataclass
class ObjectionRecord:
    """留档的反对意见及其处理结果。"""

    comment_id: str
    author_id: str
    content: str
    disposition: Disposition
    reason: str


@dataclass
class RequirementTrace:
    """已发布要求的留档:提出者、证据、异议处理、表决会议与生效日期。"""

    clause_id: str
    draft_id: str
    text: str
    version: int
    proposer_id: str
    proposal_id: str | None
    evidence_ids: list[str]
    objections: list[ObjectionRecord]
    comment_summary: dict[str, int]
    meeting_id: str | None
    vote_id: str | None
    published_by: str
    published_on: date
    effective_date: date
    withdrawal_flags: list[str] = field(default_factory=list)


@dataclass
class AffectedContent:
    """规范性引用撤回时受影响的内容。"""

    kind: str  # "draft" 或 "published"
    reference_id: str
    clause_id: str
    label: str
    status: str
