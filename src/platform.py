"""脑机接口病房标准协同编制平台。

在 `src/drafting.py` 的领域模型上执行流程规则:

- 征求意见:工作草案经作者或秘书处发起后向全体注册角色公开;
- 逐条处理:每条意见必须给出采纳/部分采纳/不采纳及理由,未处理完毕不得送审;
- 试点验证:试点证据必须脱敏,标注需要试点验证的条款无证据不得送审;
- 送审稿:只能由达到法定人数且利益冲突声明齐全的会议经表决通过后形成;
- 发布留档:每条正式要求记录提出者、证据、异议处理、表决会议与生效日期;
- 引用撤回:规范性引用撤回时精确列出受影响的草案与已发布要求;
- 角色限制:未公开草案仅作者所在角色与秘书处可见。
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Iterable

from .drafting import (
    SECRETARIAT_ROLE,
    AffectedContent,
    Actor,
    Ballot,
    Clause,
    Comment,
    CommentKind,
    Disposition,
    Draft,
    DraftingError,
    DraftStatus,
    Meeting,
    NormativeReference,
    ObjectionRecord,
    PilotEvidence,
    Proposal,
    ReferenceStatus,
    RequirementTrace,
    Term,
    Vote,
)
from .records import load_records

#: 未公开(按角色限制可见)的草案状态
_RESTRICTED_STATUSES = (DraftStatus.WORKING, DraftStatus.RETURNED)
#: 不可再进入表决/送审的终态
_TERMINAL_STATUSES = (DraftStatus.SUBMISSION, DraftStatus.PUBLISHED, DraftStatus.SUPERSEDED)


class DraftingPlatform:
    """标准工作组的协同编制平台。"""

    def __init__(self, roles: Iterable[str], approval_threshold: float = 0.75):
        if not 0 < approval_threshold <= 1:
            raise ValueError("表决通过比例应在 (0, 1] 之间")
        self.roles = set(roles) | {SECRETARIAT_ROLE}
        self.approval_threshold = approval_threshold
        self.actors: dict[str, Actor] = {}
        self.clauses: dict[str, Clause] = {}
        self.terms: dict[str, Term] = {}
        self.references: dict[str, NormativeReference] = {}
        self.proposals: dict[str, Proposal] = {}
        self.drafts: dict[str, Draft] = {}
        self.comments: dict[str, Comment] = {}
        self.evidence: dict[str, PilotEvidence] = {}
        self.meetings: dict[str, Meeting] = {}
        self.votes: dict[str, Vote] = {}
        self.archive: list[RequirementTrace] = []

    # ---- 内部检查 ----

    def _actor(self, actor_id: str) -> Actor:
        try:
            return self.actors[actor_id]
        except KeyError:
            raise DraftingError(f"未注册的参与者: {actor_id}") from None

    def _clause(self, clause_id: str) -> Clause:
        try:
            return self.clauses[clause_id]
        except KeyError:
            raise DraftingError(f"未知条款: {clause_id}") from None

    def _draft(self, draft_id: str) -> Draft:
        try:
            return self.drafts[draft_id]
        except KeyError:
            raise DraftingError(f"未知草案: {draft_id}") from None

    def _reference(self, reference_id: str) -> NormativeReference:
        try:
            return self.references[reference_id]
        except KeyError:
            raise DraftingError(f"未知规范性引用: {reference_id}") from None

    def _meeting(self, meeting_id: str) -> Meeting:
        try:
            return self.meetings[meeting_id]
        except KeyError:
            raise DraftingError(f"未知会议: {meeting_id}") from None

    def _require_secretariat(self, actor_id: str) -> Actor:
        actor = self._actor(actor_id)
        if actor.role != SECRETARIAT_ROLE:
            raise DraftingError("仅秘书处可执行该操作")
        return actor

    # ---- 基础登记 ----

    def register_actor(self, actor_id: str, name: str, role: str, organization: str) -> Actor:
        if actor_id in self.actors:
            raise DraftingError(f"参与者标识重复: {actor_id}")
        if role not in self.roles:
            raise DraftingError(f"未知协作角色: {role}")
        actor = Actor(actor_id, name, role, organization)
        self.actors[actor_id] = actor
        return actor

    def add_clause(self, clause_id: str, chapter: str, title: str, requires_pilot: bool = False) -> Clause:
        if clause_id in self.clauses:
            raise DraftingError(f"条款标识重复: {clause_id}")
        clause = Clause(clause_id, chapter, title, requires_pilot)
        self.clauses[clause_id] = clause
        return clause

    def add_term(self, term: str, definition: str, source: str = "") -> Term:
        if term in self.terms:
            raise DraftingError(f"术语重复: {term}")
        entry = Term(term, definition, source)
        self.terms[term] = entry
        return entry

    def add_reference(self, reference_id: str, code: str, title: str) -> NormativeReference:
        if reference_id in self.references:
            raise DraftingError(f"规范性引用标识重复: {reference_id}")
        reference = NormativeReference(reference_id, code, title)
        self.references[reference_id] = reference
        return reference

    # ---- 提案与并行草案 ----

    def submit_proposal(self, actor_id: str, clause_id: str, proposal_id: str,
                        summary: str, rationale: str) -> Proposal:
        self._actor(actor_id)
        self._clause(clause_id)
        if proposal_id in self.proposals:
            raise DraftingError(f"提案标识重复: {proposal_id}")
        proposal = Proposal(proposal_id, clause_id, actor_id, summary, rationale)
        self.proposals[proposal_id] = proposal
        return proposal

    def create_draft(self, actor_id: str, clause_id: str, draft_id: str, text: str,
                     reference_ids: Iterable[str] = (), visible_roles: Iterable[str] = (),
                     proposal_id: str | None = None) -> Draft:
        """为条款新建草案。同一条款允许并行草案,互不覆盖。"""
        author = self._actor(actor_id)
        self._clause(clause_id)
        if draft_id in self.drafts:
            raise DraftingError(f"草案标识重复: {draft_id}")
        unknown_roles = set(visible_roles) - self.roles
        if unknown_roles:
            raise DraftingError(f"未知协作角色: {sorted(unknown_roles)}")
        for reference_id in reference_ids:
            if self._reference(reference_id).status is ReferenceStatus.WITHDRAWN:
                raise DraftingError(f"规范性引用已撤回,不能引用: {reference_id}")
        roles = frozenset({author.role, SECRETARIAT_ROLE, *visible_roles})
        draft = Draft(draft_id, clause_id, text, actor_id,
                      visible_roles=roles, reference_ids=list(reference_ids))
        if proposal_id is not None:
            try:
                proposal = self.proposals[proposal_id]
            except KeyError:
                raise DraftingError(f"未知提案: {proposal_id}") from None
            if proposal.clause_id != clause_id:
                raise DraftingError("提案与草案条款不一致")
            if proposal.draft_id is not None:
                raise DraftingError("提案已关联草案")
            proposal.draft_id = draft_id
        self.drafts[draft_id] = draft
        return draft

    # ---- 征求意见与逐条处理 ----

    def open_for_comment(self, actor_id: str, draft_id: str) -> Draft:
        actor = self._actor(actor_id)
        draft = self._draft(draft_id)
        if actor.actor_id != draft.author_id and actor.role != SECRETARIAT_ROLE:
            raise DraftingError("仅草案作者或秘书处可发起征求意见")
        if draft.status not in (DraftStatus.WORKING, DraftStatus.RETURNED):
            raise DraftingError("当前状态不能进入征求意见")
        draft.status = DraftStatus.COMMENT
        return draft

    def submit_comment(self, actor_id: str, draft_id: str, comment_id: str,
                       content: str, kind: CommentKind = CommentKind.SUGGESTION) -> Comment:
        self._actor(actor_id)
        draft = self._draft(draft_id)
        if draft.status is not DraftStatus.COMMENT:
            raise DraftingError("草案不在征求意见阶段")
        if comment_id in self.comments:
            raise DraftingError(f"意见标识重复: {comment_id}")
        comment = Comment(comment_id, draft_id, actor_id, CommentKind(kind), content)
        self.comments[comment_id] = comment
        return comment

    def process_comment(self, handler_id: str, comment_id: str, decision: Disposition,
                        reason: str, revised_text: str | None = None) -> Comment:
        """逐条处理意见;给出修改文本时草案升版。"""
        handler = self._actor(handler_id)
        try:
            comment = self.comments[comment_id]
        except KeyError:
            raise DraftingError(f"未知意见: {comment_id}") from None
        if comment.resolved:
            raise DraftingError("意见已处理,不得重复处理")
        if not reason or not reason.strip():
            raise DraftingError("逐条处理必须说明理由")
        draft = self._draft(comment.draft_id)
        if handler.actor_id != draft.author_id and handler.role != SECRETARIAT_ROLE:
            raise DraftingError("仅草案作者或秘书处可处理意见")
        comment.disposition = Disposition(decision)
        comment.disposition_reason = reason
        comment.handler_id = handler_id
        if revised_text is not None:
            draft.text = revised_text
            draft.version += 1
        return comment

    # ---- 试点证据 ----

    def attach_evidence(self, actor_id: str, clause_id: str, evidence_id: str,
                        site: str, period: str, summary: str, deidentified: bool) -> PilotEvidence:
        self._actor(actor_id)
        self._clause(clause_id)
        if evidence_id in self.evidence:
            raise DraftingError(f"证据标识重复: {evidence_id}")
        if deidentified is not True:
            raise DraftingError("试点证据必须脱敏后方可引用")
        evidence = PilotEvidence(evidence_id, clause_id, site, period, summary, actor_id, deidentified)
        self.evidence[evidence_id] = evidence
        return evidence

    def import_observations(self, actor_id: str, observations: Iterable[dict]) -> list[str]:
        """导入脱敏观察样例为试点证据,返回证据标识列表。"""
        self._actor(actor_id)
        imported = []
        for item in observations:
            evidence = self.attach_evidence(
                actor_id, item["clause_id"], item["evidence_id"],
                item["site"], item["period"], item["summary"],
                item.get("deidentified", False),
            )
            imported.append(evidence.evidence_id)
        return imported

    # ---- 会议、利益冲突与表决 ----

    def convene_meeting(self, meeting_id: str, held_on: date,
                        attendee_ids: Iterable[str], quorum: int) -> Meeting:
        if meeting_id in self.meetings:
            raise DraftingError(f"会议标识重复: {meeting_id}")
        attendees = list(attendee_ids)
        if not attendees:
            raise DraftingError("会议至少需一名出席者")
        for actor_id in attendees:
            self._actor(actor_id)
        if quorum < 1:
            raise DraftingError("法定人数至少为1")
        meeting = Meeting(meeting_id, held_on, attendees, quorum)
        self.meetings[meeting_id] = meeting
        return meeting

    def declare_coi(self, meeting_id: str, actor_id: str) -> Meeting:
        meeting = self._meeting(meeting_id)
        self._actor(actor_id)
        if actor_id not in meeting.attendee_ids:
            raise DraftingError("仅会议出席者需声明利益冲突")
        meeting.coi_declared.add(actor_id)
        return meeting

    def open_vote(self, meeting_id: str, vote_id: str, draft_id: str) -> Vote:
        self._meeting(meeting_id)
        draft = self._draft(draft_id)
        if vote_id in self.votes:
            raise DraftingError(f"表决标识重复: {vote_id}")
        if draft.status in _TERMINAL_STATUSES:
            raise DraftingError("该草案当前状态不可表决")
        if any(v.meeting_id == meeting_id and v.draft_id == draft_id for v in self.votes.values()):
            raise DraftingError("该会议已对本草案发起表决")
        vote = Vote(vote_id, meeting_id, draft_id)
        self.votes[vote_id] = vote
        return vote

    def cast_vote(self, meeting_id: str, vote_id: str, actor_id: str, ballot: Ballot) -> Vote:
        meeting = self._meeting(meeting_id)
        self._actor(actor_id)
        try:
            vote = self.votes[vote_id]
        except KeyError:
            raise DraftingError(f"未知表决: {vote_id}") from None
        if vote.meeting_id != meeting_id:
            raise DraftingError("表决不属于该会议")
        if actor_id not in meeting.attendee_ids:
            raise DraftingError("仅会议出席者可表决")
        if actor_id in vote.ballots:
            raise DraftingError("不得重复表决")
        vote.ballots[actor_id] = Ballot(ballot)
        return vote

    def _vote_passed(self, vote: Vote) -> bool:
        total = len(vote.ballots)
        if total == 0:
            return False
        approve = sum(1 for ballot in vote.ballots.values() if ballot is Ballot.APPROVE)
        return approve >= math.ceil(self.approval_threshold * total)

    def elevate_to_submission(self, actor_id: str, draft_id: str, meeting_id: str) -> Draft:
        """形成送审稿。只能来自完成利益冲突声明且达到法定人数的会议,
        且意见逐条处理完毕、试点证据齐备、表决通过。"""
        self._require_secretariat(actor_id)
        draft = self._draft(draft_id)
        meeting = self._meeting(meeting_id)
        if draft.status in _TERMINAL_STATUSES:
            raise DraftingError("该草案当前状态不可送审")
        if not meeting.is_quorate:
            raise DraftingError(
                f"会议未达到法定人数({len(set(meeting.attendee_ids))}/{meeting.quorum})")
        missing_coi = [a for a in meeting.attendee_ids if a not in meeting.coi_declared]
        if missing_coi:
            raise DraftingError(f"利益冲突声明未齐全: {missing_coi}")
        unresolved = [c.comment_id for c in self.comments.values()
                      if c.draft_id == draft_id and not c.resolved]
        if unresolved:
            raise DraftingError(f"存在未处理意见: {unresolved}")
        clause = self._clause(draft.clause_id)
        if clause.requires_pilot and not any(
                e.clause_id == clause.clause_id for e in self.evidence.values()):
            raise DraftingError("该条款要求试点验证,尚无试点证据")
        vote = next((v for v in self.votes.values()
                     if v.meeting_id == meeting_id and v.draft_id == draft_id), None)
        if vote is None:
            raise DraftingError("该会议尚未对本草案表决")
        if not self._vote_passed(vote):
            draft.status = DraftStatus.RETURNED
            raise DraftingError("表决未通过,草案退回修改")
        draft.status = DraftStatus.SUBMISSION
        draft.meeting_id = meeting_id
        draft.vote_id = vote.vote_id
        return draft

    # ---- 规范性引用撤回 ----

    def withdraw_reference(self, actor_id: str, reference_id: str) -> list[AffectedContent]:
        """撤回规范性引用,精确列出受影响的未发布草案与已发布要求并打标。"""
        self._require_secretariat(actor_id)
        reference = self._reference(reference_id)
        reference.status = ReferenceStatus.WITHDRAWN
        affected: list[AffectedContent] = []
        for draft in self.drafts.values():
            if reference_id not in draft.reference_ids:
                continue
            if draft.status in (DraftStatus.PUBLISHED, DraftStatus.SUPERSEDED):
                continue  # 已发布内容由下方留档记录覆盖
            if reference_id not in draft.withdrawal_flags:
                draft.withdrawal_flags.append(reference_id)
            affected.append(AffectedContent(
                "draft", reference_id, draft.clause_id, draft.draft_id, draft.status.value))
        for trace in self.archive:
            if reference_id not in self.drafts[trace.draft_id].reference_ids:
                continue
            if reference_id not in trace.withdrawal_flags:
                trace.withdrawal_flags.append(reference_id)
            affected.append(AffectedContent(
                "published", reference_id, trace.clause_id, trace.draft_id, "published"))
        return affected

    # ---- 发布与留档 ----

    def publish(self, actor_id: str, draft_id: str,
                published_on: date, effective_date: date) -> RequirementTrace:
        """发布送审稿并留档;同条款旧版已发布要求自动转为被替代。"""
        self._require_secretariat(actor_id)
        draft = self._draft(draft_id)
        if draft.status is not DraftStatus.SUBMISSION:
            raise DraftingError("仅送审稿可发布")
        if effective_date < published_on:
            raise DraftingError("生效日期不得早于发布日期")
        for other in self.drafts.values():
            if other.clause_id == draft.clause_id and other.status is DraftStatus.PUBLISHED:
                other.status = DraftStatus.SUPERSEDED
        draft.status = DraftStatus.PUBLISHED

        clause_comments = [c for c in self.comments.values() if c.draft_id == draft_id]
        objections = [
            ObjectionRecord(c.comment_id, c.author_id, c.content, c.disposition, c.disposition_reason)
            for c in clause_comments if c.kind is CommentKind.OBJECTION
        ]
        summary = {d.value: 0 for d in Disposition}
        for comment in clause_comments:
            if comment.disposition is not None:
                summary[comment.disposition.value] += 1
        proposal_id = next((p.proposal_id for p in self.proposals.values()
                            if p.draft_id == draft_id), None)
        proposer_id = self.proposals[proposal_id].proposer_id if proposal_id else draft.author_id
        evidence_ids = [e.evidence_id for e in self.evidence.values()
                        if e.clause_id == draft.clause_id]
        trace = RequirementTrace(
            clause_id=draft.clause_id,
            draft_id=draft_id,
            text=draft.text,
            version=draft.version,
            proposer_id=proposer_id,
            proposal_id=proposal_id,
            evidence_ids=evidence_ids,
            objections=objections,
            comment_summary=summary,
            meeting_id=draft.meeting_id,
            vote_id=draft.vote_id,
            published_by=actor_id,
            published_on=published_on,
            effective_date=effective_date,
            withdrawal_flags=list(draft.withdrawal_flags),
        )
        self.archive.append(trace)
        return trace

    def trace_requirement(self, clause_id: str) -> RequirementTrace:
        """返回条款当前生效要求的留档,可说明提出者、证据、异议处理及生效日期。"""
        traces = [t for t in self.archive if t.clause_id == clause_id]
        if not traces:
            raise DraftingError(f"条款尚无已发布要求: {clause_id}")
        return traces[-1]

    # ---- 角色可见性 ----

    def can_view(self, actor_id: str, draft_id: str) -> bool:
        actor = self._actor(actor_id)
        draft = self._draft(draft_id)
        if draft.status in _RESTRICTED_STATUSES:
            return actor.actor_id == draft.author_id or actor.role in draft.visible_roles
        return True

    def visible_drafts(self, actor_id: str) -> list[Draft]:
        self._actor(actor_id)
        return sorted((d for d in self.drafts.values() if self.can_view(actor_id, d.draft_id)),
                      key=lambda d: d.draft_id)


def platform_from_context(path: str | Path) -> DraftingPlatform:
    """依据共享领域资料中的协作角色建立平台。"""
    data = load_records(Path(path))
    return DraftingPlatform(roles=data["actors"])
