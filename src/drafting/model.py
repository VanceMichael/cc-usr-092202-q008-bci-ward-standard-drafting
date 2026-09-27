"""脑机病房标准编制平台的数据结构。

覆盖章节、术语、规范性引用、提案、意见、反对意见、
试点证据、会议与表决以及发布留档所需的全部记录。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class Role(str, Enum):
    """协作角色，与公开样例的参与者类别一致。"""

    CLINICAL = "临床科室"
    ETHICS = "伦理委员会"
    RESEARCH = "科研团队"
    VENDOR = "设备企业"
    SUBJECT_MANAGER = "受试者管理人员"


class DraftStatus(str, Enum):
    INTERNAL = "未公开"
    CONSULTING = "征求意见"
    SUBMISSION = "送审稿"
    PUBLISHED = "已发布"
    SUPERSEDED = "被替代"


class Disposition(str, Enum):
    """征求意见的逐条处理结论。"""

    PENDING = "待处理"
    ADOPTED = "采纳"
    PARTIAL = "部分采纳"
    REJECTED = "不采纳"


class ObjectionStatus(str, Enum):
    OPEN = "待处理"
    ADOPTED = "采纳并修改"
    REJECTED = "不采纳并说明"
    WITHDRAWN = "异议方撤回"


class EvidenceStatus(str, Enum):
    REGISTERED = "已登记"
    VERIFIED = "验证通过"
    FAILED = "验证未通过"


class ReferenceStatus(str, Enum):
    CURRENT = "现行"
    WITHDRAWN = "已撤回"


class VoteChoice(str, Enum):
    APPROVE = "赞成"
    REJECT = "反对"
    ABSTAIN = "弃权"


@dataclass
class Participant:
    """参与编制的机构代表，label 使用脱敏代号。"""

    id: str
    label: str
    role: Role
    in_working_group: bool = False


@dataclass
class Clause:
    """标准条款，允许挂多份并行草案。"""

    id: str
    chapter: str
    title: str
    requires_pilot: bool = False
    reference_ids: list[str] = field(default_factory=list)
    withdrawn_reference_ids: list[str] = field(default_factory=list)
    withdrawal_handling: list[str] = field(default_factory=list)


@dataclass
class Draft:
    """条款草案；未公开时仅对 visible_roles 与作者可见。"""

    id: str
    clause_id: str
    author_id: str
    text: str
    status: DraftStatus = DraftStatus.INTERNAL
    visible_roles: set[Role] = field(default_factory=set)
    approved_meeting_id: str | None = None


@dataclass
class Term:
    id: str
    name: str
    definition: str
    source_draft_id: str | None = None


@dataclass
class NormativeReference:
    id: str
    code: str
    title: str
    status: ReferenceStatus = ReferenceStatus.CURRENT


@dataclass
class Proposal:
    """针对条款的编制提案。"""

    id: str
    clause_id: str
    author_id: str
    body: str


@dataclass
class Opinion:
    """征求意见阶段收到的意见，需逐条处理。"""

    id: str
    draft_id: str
    author_id: str
    body: str
    disposition: Disposition = Disposition.PENDING
    disposition_reason: str = ""
    handler_id: str | None = None


@dataclass
class Objection:
    """反对意见，了结方式写入正式要求的溯源信息。"""

    id: str
    draft_id: str
    author_id: str
    body: str
    status: ObjectionStatus = ObjectionStatus.OPEN
    resolution: str = ""
    handler_id: str | None = None


@dataclass
class PilotEvidence:
    """试点证据，site_code 为脱敏后的机构代号。"""

    id: str
    clause_id: str
    site_code: str
    summary: str
    status: EvidenceStatus = EvidenceStatus.REGISTERED
    note: str = ""


@dataclass
class Vote:
    voter_id: str
    choice: VoteChoice


@dataclass
class Meeting:
    """编制会议；只有声明齐全且达到法定人数才能产生送审稿。"""

    id: str
    held_on: date
    attendee_ids: list[str]
    quorum: int
    coi_declarations: dict[str, str] = field(default_factory=dict)
    votes: dict[str, list[Vote]] = field(default_factory=dict)


@dataclass
class Requirement:
    """正式发布的要求，保留提出者、证据、异议处理与生效日期。"""

    id: str
    clause_id: str
    draft_id: str
    text: str
    proposer_id: str
    evidence_ids: list[str]
    objection_handling: list[str]
    effective_date: date
    published_on: date
