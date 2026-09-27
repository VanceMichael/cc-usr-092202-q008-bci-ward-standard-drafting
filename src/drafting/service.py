"""协同编制平台的核心流程：征求意见、逐条处理、试点验证、表决与发布留档。"""

from __future__ import annotations

from datetime import date

from src.drafting.errors import (
    DraftVisibilityError,
    EvidenceNotVerifiedError,
    InvalidTransitionError,
    MeetingNotReadyError,
    UnresolvedFeedbackError,
    VoteThresholdError,
    WithdrawnReferenceError,
)
from src.drafting.model import (
    Clause,
    Disposition,
    Draft,
    DraftStatus,
    EvidenceStatus,
    Meeting,
    NormativeReference,
    Objection,
    ObjectionStatus,
    Opinion,
    Participant,
    PilotEvidence,
    Proposal,
    ReferenceStatus,
    Requirement,
    Role,
    Term,
    Vote,
    VoteChoice,
)

#: 送审稿表决通过门槛：赞成票占有效票（赞成+反对）的比例
VOTE_THRESHOLD = 2 / 3


class DraftingPlatform:
    """保存标准编制全过程资料并执行关键门禁。"""

    def __init__(self) -> None:
        self.participants: dict[str, Participant] = {}
        self.clauses: dict[str, Clause] = {}
        self.drafts: dict[str, Draft] = {}
        self.terms: dict[str, Term] = {}
        self.references: dict[str, NormativeReference] = {}
        self.proposals: dict[str, Proposal] = {}
        self.opinions: dict[str, Opinion] = {}
        self.objections: dict[str, Objection] = {}
        self.evidence: dict[str, PilotEvidence] = {}
        self.meetings: dict[str, Meeting] = {}
        self.requirements: dict[str, Requirement] = {}
        self.archives: list[dict] = []
        self._seq = 0

    def _next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq:04d}"

    # ---- 参与者与基础资料 ----

    def register_participant(
        self, label: str, role: Role, in_working_group: bool = False
    ) -> Participant:
        participant = Participant(
            id=self._next_id("actor"), label=label, role=role,
            in_working_group=in_working_group,
        )
        self.participants[participant.id] = participant
        return participant

    def add_clause(self, chapter: str, title: str, requires_pilot: bool = False) -> Clause:
        clause = Clause(
            id=self._next_id("clause"), chapter=chapter, title=title,
            requires_pilot=requires_pilot,
        )
        self.clauses[clause.id] = clause
        return clause

    def add_term(self, name: str, definition: str, source_draft_id: str | None = None) -> Term:
        term = Term(
            id=self._next_id("term"), name=name, definition=definition,
            source_draft_id=source_draft_id,
        )
        self.terms[term.id] = term
        return term

    def add_reference(self, code: str, title: str) -> NormativeReference:
        reference = NormativeReference(id=self._next_id("ref"), code=code, title=title)
        self.references[reference.id] = reference
        return reference

    def cite_reference(self, clause_id: str, reference_id: str) -> None:
        clause = self.clauses[clause_id]
        if reference_id not in clause.reference_ids:
            clause.reference_ids.append(reference_id)

    # ---- 并行草案与角色可见性 ----

    def create_draft(
        self,
        clause_id: str,
        author_id: str,
        text: str,
        visible_roles: set[Role] | None = None,
    ) -> Draft:
        """为条款创建并行草案；未公开时默认仅作者所在角色可见。"""
        author = self.participants[author_id]
        draft = Draft(
            id=self._next_id("draft"), clause_id=clause_id, author_id=author_id,
            text=text,
            visible_roles=set(visible_roles) if visible_roles else {author.role},
        )
        self.drafts[draft.id] = draft
        return draft

    def get_draft(self, draft_id: str, participant_id: str) -> Draft:
        """按角色限制未公开草案的访问；征求意见及之后全员可见。"""
        draft = self.drafts[draft_id]
        if draft.status is DraftStatus.INTERNAL:
            participant = self.participants[participant_id]
            allowed = set(draft.visible_roles)
            allowed.add(self.participants[draft.author_id].role)
            if participant.role not in allowed and participant_id != draft.author_id:
                raise DraftVisibilityError(
                    f"草案 {draft_id} 尚未公开，角色 {participant.role.value} 不可见"
                )
        return draft

    def open_consultation(self, draft_id: str) -> Draft:
        """将未公开草案转入征求意见，向全部角色开放。"""
        draft = self.drafts[draft_id]
        if draft.status is not DraftStatus.INTERNAL:
            raise InvalidTransitionError(f"草案 {draft_id} 当前状态不能转入征求意见")
        draft.status = DraftStatus.CONSULTING
        return draft

    # ---- 提案、征求意见与逐条处理 ----

    def submit_proposal(self, clause_id: str, author_id: str, body: str) -> Proposal:
        proposal = Proposal(
            id=self._next_id("proposal"), clause_id=clause_id,
            author_id=author_id, body=body,
        )
        self.proposals[proposal.id] = proposal
        return proposal

    def submit_opinion(self, draft_id: str, author_id: str, body: str) -> Opinion:
        draft = self.drafts[draft_id]
        if draft.status is not DraftStatus.CONSULTING:
            raise InvalidTransitionError(f"草案 {draft_id} 不在征求意见阶段")
        opinion = Opinion(
            id=self._next_id("opinion"), draft_id=draft_id,
            author_id=author_id, body=body,
        )
        self.opinions[opinion.id] = opinion
        return opinion

    def handle_opinion(
        self, opinion_id: str, handler_id: str, disposition: Disposition, reason: str
    ) -> Opinion:
        """逐条处理意见，处理结论与理由留档。"""
        opinion = self.opinions[opinion_id]
        if disposition is Disposition.PENDING:
            raise InvalidTransitionError("处理结论不能为待处理")
        opinion.disposition = disposition
        opinion.disposition_reason = reason
        opinion.handler_id = handler_id
        return opinion

    def submit_objection(self, draft_id: str, author_id: str, body: str) -> Objection:
        objection = Objection(
            id=self._next_id("objection"), draft_id=draft_id,
            author_id=author_id, body=body,
        )
        self.objections[objection.id] = objection
        return objection

    def resolve_objection(
        self, objection_id: str, handler_id: str, status: ObjectionStatus, resolution: str
    ) -> Objection:
        objection = self.objections[objection_id]
        if status is ObjectionStatus.OPEN:
            raise InvalidTransitionError("异议了结方式不能为待处理")
        objection.status = status
        objection.resolution = resolution
        objection.handler_id = handler_id
        return objection

    # ---- 试点验证 ----

    def register_evidence(self, clause_id: str, site_code: str, summary: str) -> PilotEvidence:
        evidence = PilotEvidence(
            id=self._next_id("evidence"), clause_id=clause_id,
            site_code=site_code, summary=summary,
        )
        self.evidence[evidence.id] = evidence
        return evidence

    def verify_evidence(self, evidence_id: str, passed: bool, note: str = "") -> PilotEvidence:
        evidence = self.evidence[evidence_id]
        evidence.status = EvidenceStatus.VERIFIED if passed else EvidenceStatus.FAILED
        evidence.note = note
        return evidence

    # ---- 规范性引用撤回 ----

    def withdraw_reference(self, reference_id: str) -> list[Clause]:
        """撤回规范性引用，返回受影响的条款并阻断其送审。"""
        reference = self.references[reference_id]
        reference.status = ReferenceStatus.WITHDRAWN
        impacted = []
        for clause in self.clauses.values():
            if reference_id in clause.reference_ids:
                if reference_id not in clause.withdrawn_reference_ids:
                    clause.withdrawn_reference_ids.append(reference_id)
                impacted.append(clause)
        return impacted

    def acknowledge_withdrawal(self, clause_id: str, reference_id: str, note: str) -> Clause:
        """记录撤回引用的处理结果（替换引用或改写条款）后解除阻断。"""
        clause = self.clauses[clause_id]
        if reference_id in clause.withdrawn_reference_ids:
            clause.withdrawn_reference_ids.remove(reference_id)
        clause.withdrawal_handling.append(f"{reference_id}: {note}")
        return clause

    # ---- 会议、利益冲突声明与表决 ----

    def convene_meeting(
        self, held_on: date, attendee_ids: list[str], quorum: int
    ) -> Meeting:
        meeting = Meeting(
            id=self._next_id("meeting"), held_on=held_on,
            attendee_ids=list(attendee_ids), quorum=quorum,
        )
        self.meetings[meeting.id] = meeting
        return meeting

    def declare_coi(self, meeting_id: str, participant_id: str, statement: str) -> Meeting:
        """登记与会者的利益冲突声明。"""
        meeting = self.meetings[meeting_id]
        if participant_id not in meeting.attendee_ids:
            raise InvalidTransitionError(f"参与者 {participant_id} 不在会议 {meeting_id} 出席名单")
        meeting.coi_declarations[participant_id] = statement
        return meeting

    def meeting_ready(self, meeting_id: str) -> bool:
        """法定人数以出席的编制组成员计，且全体出席者均已声明利益冲突。"""
        meeting = self.meetings[meeting_id]
        wg_present = sum(
            1 for pid in meeting.attendee_ids if self.participants[pid].in_working_group
        )
        declared = all(pid in meeting.coi_declarations for pid in meeting.attendee_ids)
        return wg_present >= meeting.quorum and declared

    def cast_vote(
        self, meeting_id: str, draft_id: str, voter_id: str, choice: VoteChoice
    ) -> None:
        meeting = self.meetings[meeting_id]
        if voter_id not in meeting.attendee_ids:
            raise InvalidTransitionError(f"参与者 {voter_id} 不在会议 {meeting_id} 出席名单")
        ballot = meeting.votes.setdefault(draft_id, [])
        ballot[:] = [v for v in ballot if v.voter_id != voter_id]
        ballot.append(Vote(voter_id=voter_id, choice=choice))

    # ---- 送审稿与发布留档 ----

    def approve_submission(self, draft_id: str, meeting_id: str) -> Draft:
        """把征求意见后的草案确认为送审稿，逐项检查法定条件。"""
        draft = self.drafts[draft_id]
        if draft.status is not DraftStatus.CONSULTING:
            raise InvalidTransitionError(f"草案 {draft_id} 不在征求意见阶段")
        if not self.meeting_ready(meeting_id):
            raise MeetingNotReadyError("会议未完成利益冲突声明或未达到法定人数")

        pending = [
            o.id for o in self.opinions.values()
            if o.draft_id == draft_id and o.disposition is Disposition.PENDING
        ]
        open_objections = [
            o.id for o in self.objections.values()
            if o.draft_id == draft_id and o.status is ObjectionStatus.OPEN
        ]
        if pending or open_objections:
            raise UnresolvedFeedbackError(
                f"存在未处理意见 {pending} 或未了结异议 {open_objections}"
            )

        clause = self.clauses[draft.clause_id]
        if clause.requires_pilot and not any(
            e.clause_id == clause.id and e.status is EvidenceStatus.VERIFIED
            for e in self.evidence.values()
        ):
            raise EvidenceNotVerifiedError(f"条款 {clause.id} 缺少验证通过的试点证据")
        if clause.withdrawn_reference_ids:
            raise WithdrawnReferenceError(
                f"条款 {clause.id} 存在未处理的撤回引用 {clause.withdrawn_reference_ids}"
            )

        meeting = self.meetings[meeting_id]
        ballots = [
            v for v in meeting.votes.get(draft_id, [])
            if self.participants[v.voter_id].in_working_group
        ]
        approve = sum(1 for v in ballots if v.choice is VoteChoice.APPROVE)
        reject = sum(1 for v in ballots if v.choice is VoteChoice.REJECT)
        if not ballots or approve < VOTE_THRESHOLD * (approve + reject):
            raise VoteThresholdError(
                f"草案 {draft_id} 表决未通过：赞成 {approve}，反对 {reject}"
            )

        draft.status = DraftStatus.SUBMISSION
        draft.approved_meeting_id = meeting_id
        return draft

    def publish(
        self, draft_id: str, effective_date: date, published_on: date | None = None
    ) -> Requirement:
        """发布送审稿，形成带完整溯源信息的正式要求并留档。"""
        draft = self.drafts[draft_id]
        if draft.status is not DraftStatus.SUBMISSION:
            raise InvalidTransitionError(f"草案 {draft_id} 不是送审稿，不能发布")
        published_on = published_on or date.today()
        clause = self.clauses[draft.clause_id]

        objection_handling = [
            f"{o.id} {o.status.value}：{o.resolution}"
            for o in self.objections.values()
            if o.draft_id == draft_id
        ]
        evidence_ids = [
            e.id for e in self.evidence.values()
            if e.clause_id == clause.id and e.status is EvidenceStatus.VERIFIED
        ]
        requirement = Requirement(
            id=self._next_id("requirement"), clause_id=clause.id, draft_id=draft_id,
            text=draft.text, proposer_id=draft.author_id,
            evidence_ids=evidence_ids, objection_handling=objection_handling,
            effective_date=effective_date, published_on=published_on,
        )
        self.requirements[requirement.id] = requirement

        for other in self.drafts.values():
            if (
                other.clause_id == clause.id
                and other.status is DraftStatus.PUBLISHED
            ):
                other.status = DraftStatus.SUPERSEDED
        draft.status = DraftStatus.PUBLISHED

        self.archives.append({
            "requirement_id": requirement.id,
            "clause": f"{clause.chapter} {clause.title}",
            "text": requirement.text,
            "source_draft_id": draft_id,
            "approved_meeting_id": draft.approved_meeting_id,
            "published_on": published_on.isoformat(),
            "effective_date": effective_date.isoformat(),
        })
        return requirement

    # ---- 溯源 ----

    def requirement_trace(self, requirement_id: str) -> dict:
        """回答正式要求的提出者、证据、异议处理及生效日期。"""
        requirement = self.requirements[requirement_id]
        proposer = self.participants[requirement.proposer_id]
        return {
            "要求": requirement.text,
            "提出者": f"{proposer.label}（{proposer.role.value}）",
            "证据": [
                f"{e.site_code}：{e.summary}"
                for e in (self.evidence[eid] for eid in requirement.evidence_ids)
            ],
            "异议处理": list(requirement.objection_handling),
            "生效日期": requirement.effective_date.isoformat(),
        }
