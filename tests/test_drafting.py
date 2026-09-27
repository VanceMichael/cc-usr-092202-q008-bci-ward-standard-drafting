import unittest
from datetime import date

from src.drafting import (
    Disposition,
    DraftingPlatform,
    DraftStatus,
    DraftVisibilityError,
    EvidenceNotVerifiedError,
    InvalidTransitionError,
    MeetingNotReadyError,
    ObjectionStatus,
    Role,
    UnresolvedFeedbackError,
    VoteChoice,
    VoteThresholdError,
    WithdrawnReferenceError,
)

MEETING_DAY = date(2026, 8, 20)
EFFECTIVE_DAY = date(2026, 12, 1)


def make_platform():
    """按公开样例中的五类角色建立脱敏参与者。"""
    platform = DraftingPlatform()
    actors = {
        "clinical": platform.register_participant(
            "某三甲医院神经内科", Role.CLINICAL, in_working_group=True
        ),
        "ethics": platform.register_participant(
            "某机构伦理委员会", Role.ETHICS, in_working_group=True
        ),
        "research": platform.register_participant(
            "某高校科研团队", Role.RESEARCH, in_working_group=True
        ),
        "vendor": platform.register_participant(
            "某设备企业", Role.VENDOR, in_working_group=True
        ),
        "subject": platform.register_participant(
            "受试者管理代表", Role.SUBJECT_MANAGER
        ),
    }
    return platform, actors


def ready_meeting(platform, actors, quorum=3):
    """召开声明齐全且达到法定人数的会议。"""
    meeting = platform.convene_meeting(
        MEETING_DAY,
        [actors[key].id for key in ("clinical", "ethics", "research", "vendor")],
        quorum,
    )
    for key in ("clinical", "ethics", "research", "vendor"):
        platform.declare_coi(meeting.id, actors[key].id, "无相关经济利益")
    return meeting


class VisibilityTest(unittest.TestCase):
    def test_parallel_drafts_and_role_restriction(self):
        platform, actors = make_platform()
        clause = platform.add_clause("第5章", "病房分区")
        draft_a = platform.create_draft(clause.id, actors["research"].id, "方案甲")
        draft_b = platform.create_draft(clause.id, actors["clinical"].id, "方案乙")
        self.assertNotEqual(draft_a.id, draft_b.id, "同一条款应允许并行草案")

        # 未公开草案：作者角色可见，其他角色受限
        platform.get_draft(draft_a.id, actors["research"].id)
        with self.assertRaises(DraftVisibilityError):
            platform.get_draft(draft_a.id, actors["vendor"].id)
        with self.assertRaises(DraftVisibilityError):
            platform.get_draft(draft_a.id, actors["subject"].id)

        # 进入征求意见后全员可见
        platform.open_consultation(draft_a.id)
        platform.get_draft(draft_a.id, actors["vendor"].id)
        platform.get_draft(draft_a.id, actors["subject"].id)


class ConsultationTest(unittest.TestCase):
    def setUp(self):
        self.platform, self.actors = make_platform()
        self.clause = self.platform.add_clause("第6章", "人员配置")
        self.draft = self.platform.create_draft(
            self.clause.id, self.actors["clinical"].id, "每病房至少2名受训护士"
        )
        self.platform.open_consultation(self.draft.id)

    def test_opinions_must_be_handled_one_by_one(self):
        opinion = self.platform.submit_opinion(
            self.draft.id, self.actors["vendor"].id, "建议明确受训学时"
        )
        meeting = ready_meeting(self.platform, self.actors)
        for key in ("clinical", "ethics", "research"):
            self.platform.cast_vote(
                meeting.id, self.draft.id, self.actors[key].id, VoteChoice.APPROVE
            )
        with self.assertRaises(UnresolvedFeedbackError):
            self.platform.approve_submission(self.draft.id, meeting.id)

        self.platform.handle_opinion(
            opinion.id, self.actors["clinical"].id, Disposition.ADOPTED, "已补充学时要求"
        )
        self.platform.approve_submission(self.draft.id, meeting.id)
        self.assertEqual(self.draft.status, DraftStatus.SUBMISSION)

    def test_opinion_only_accepted_during_consultation(self):
        with self.assertRaises(InvalidTransitionError):
            self.platform.submit_opinion(
                self.platform.create_draft(
                    self.clause.id, self.actors["research"].id, "内部稿"
                ).id,
                self.actors["vendor"].id,
                "不应收到",
            )

    def test_objection_must_be_resolved(self):
        objection = self.platform.submit_objection(
            self.draft.id, self.actors["ethics"].id, "未覆盖夜间值守伦理风险"
        )
        meeting = ready_meeting(self.platform, self.actors)
        for key in ("clinical", "ethics", "research"):
            self.platform.cast_vote(
                meeting.id, self.draft.id, self.actors[key].id, VoteChoice.APPROVE
            )
        with self.assertRaises(UnresolvedFeedbackError):
            self.platform.approve_submission(self.draft.id, meeting.id)

        self.platform.resolve_objection(
            objection.id, self.actors["clinical"].id,
            ObjectionStatus.ADOPTED, "已增加夜间值守条款",
        )
        self.platform.approve_submission(self.draft.id, meeting.id)


class MeetingGateTest(unittest.TestCase):
    def setUp(self):
        self.platform, self.actors = make_platform()
        self.clause = self.platform.add_clause("第7章", "患者筛选")
        self.draft = self.platform.create_draft(
            self.clause.id, self.actors["clinical"].id, "入选前完成认知评估"
        )
        self.platform.open_consultation(self.draft.id)

    def test_missing_coi_declaration_blocks_submission(self):
        meeting = self.platform.convene_meeting(
            MEETING_DAY,
            [self.actors[k].id for k in ("clinical", "ethics", "research", "vendor")],
            3,
        )
        for key in ("clinical", "ethics", "research"):
            self.platform.declare_coi(meeting.id, self.actors[key].id, "无")
        self.assertFalse(self.platform.meeting_ready(meeting.id))
        with self.assertRaises(MeetingNotReadyError):
            self.platform.approve_submission(self.draft.id, meeting.id)

    def test_quorum_counts_working_group_members(self):
        meeting = self.platform.convene_meeting(
            MEETING_DAY,
            [self.actors["clinical"].id, self.actors["subject"].id],
            2,
        )
        for key in ("clinical", "subject"):
            self.platform.declare_coi(meeting.id, self.actors[key].id, "无")
        # 出席者中编制组成员只有1人，未达法定人数
        self.assertFalse(self.platform.meeting_ready(meeting.id))

    def test_vote_threshold(self):
        meeting = ready_meeting(self.platform, self.actors)
        self.platform.cast_vote(
            meeting.id, self.draft.id, self.actors["clinical"].id, VoteChoice.APPROVE
        )
        self.platform.cast_vote(
            meeting.id, self.draft.id, self.actors["ethics"].id, VoteChoice.REJECT
        )
        self.platform.cast_vote(
            meeting.id, self.draft.id, self.actors["research"].id, VoteChoice.REJECT
        )
        self.platform.cast_vote(
            meeting.id, self.draft.id, self.actors["vendor"].id, VoteChoice.ABSTAIN
        )
        with self.assertRaises(VoteThresholdError):
            self.platform.approve_submission(self.draft.id, meeting.id)


class PilotEvidenceTest(unittest.TestCase):
    def test_pilot_clause_requires_verified_evidence(self):
        platform, actors = make_platform()
        clause = platform.add_clause("第8章", "异常处置", requires_pilot=True)
        draft = platform.create_draft(clause.id, actors["clinical"].id, "癫痫样放电即刻停机")
        platform.open_consultation(draft.id)
        meeting = ready_meeting(platform, actors)
        for key in ("clinical", "ethics", "research"):
            platform.cast_vote(
                meeting.id, draft.id, actors[key].id, VoteChoice.APPROVE
            )

        with self.assertRaises(EvidenceNotVerifiedError):
            platform.approve_submission(draft.id, meeting.id)

        evidence = platform.register_evidence(
            clause.id, "试点机构A", "3个月处置演练记录"
        )
        platform.verify_evidence(evidence.id, passed=False, note="样本量不足")
        with self.assertRaises(EvidenceNotVerifiedError):
            platform.approve_submission(draft.id, meeting.id)

        platform.verify_evidence(evidence.id, passed=True, note="复核通过")
        platform.approve_submission(draft.id, meeting.id)


class WithdrawalTest(unittest.TestCase):
    def test_withdrawn_reference_flags_and_blocks(self):
        platform, actors = make_platform()
        clause = platform.add_clause("第9章", "数据保存")
        reference = platform.add_reference("GB/T XXXX", "健康数据存储要求")
        platform.cite_reference(clause.id, reference.id)
        draft = platform.create_draft(clause.id, actors["research"].id, "原始数据保存十年")
        platform.open_consultation(draft.id)
        meeting = ready_meeting(platform, actors)
        for key in ("clinical", "ethics", "research"):
            platform.cast_vote(
                meeting.id, draft.id, actors[key].id, VoteChoice.APPROVE
            )

        impacted = platform.withdraw_reference(reference.id)
        self.assertEqual([c.id for c in impacted], [clause.id])
        with self.assertRaises(WithdrawnReferenceError):
            platform.approve_submission(draft.id, meeting.id)

        platform.acknowledge_withdrawal(clause.id, reference.id, "改引新版国标")
        platform.approve_submission(draft.id, meeting.id)


class PublishTraceTest(unittest.TestCase):
    def test_publish_archives_full_traceability(self):
        platform, actors = make_platform()
        clause = platform.add_clause("第9章", "数据保存", requires_pilot=True)
        reference = platform.add_reference("GB/T YYYY", "个人信息去标识化指南")
        platform.cite_reference(clause.id, reference.id)
        platform.submit_proposal(
            clause.id, actors["clinical"].id, "建议区分原始数据与衍生数据保存期"
        )
        draft = platform.create_draft(
            clause.id, actors["clinical"].id, "原始信号保存不少于十年"
        )
        platform.open_consultation(draft.id)
        opinion = platform.submit_opinion(
            draft.id, actors["vendor"].id, "保存期建议与设备日志对齐"
        )
        platform.handle_opinion(
            opinion.id, actors["clinical"].id, Disposition.PARTIAL, "采纳日志对齐部分"
        )
        objection = platform.submit_objection(
            draft.id, actors["ethics"].id, "十年保存期超出最小必要原则"
        )
        platform.resolve_objection(
            objection.id, actors["clinical"].id,
            ObjectionStatus.REJECTED, "依据在研项目伦理批件，维持十年",
        )
        evidence = platform.register_evidence(
            clause.id, "试点机构B", "两年存储运行零丢失"
        )
        platform.verify_evidence(evidence.id, passed=True)
        meeting = ready_meeting(platform, actors)
        for key in ("clinical", "ethics", "research"):
            platform.cast_vote(
                meeting.id, draft.id, actors[key].id, VoteChoice.APPROVE
            )
        platform.cast_vote(
            meeting.id, draft.id, actors["vendor"].id, VoteChoice.ABSTAIN
        )
        platform.approve_submission(draft.id, meeting.id)

        requirement = platform.publish(draft.id, EFFECTIVE_DAY, published_on=MEETING_DAY)
        trace = platform.requirement_trace(requirement.id)
        self.assertIn("某三甲医院神经内科", trace["提出者"])
        self.assertEqual(trace["证据"], ["试点机构B：两年存储运行零丢失"])
        self.assertEqual(len(trace["异议处理"]), 1)
        self.assertIn("维持十年", trace["异议处理"][0])
        self.assertEqual(trace["生效日期"], "2026-12-01")

        self.assertEqual(len(platform.archives), 1)
        self.assertEqual(platform.archives[0]["approved_meeting_id"], meeting.id)

        # 新版本发布后旧版本被替代
        draft_v2 = platform.create_draft(
            clause.id, actors["clinical"].id, "原始信号保存不少于十五年"
        )
        platform.open_consultation(draft_v2.id)
        meeting2 = ready_meeting(platform, actors)
        for key in ("clinical", "ethics", "research"):
            platform.cast_vote(
                meeting2.id, draft_v2.id, actors[key].id, VoteChoice.APPROVE
            )
        platform.approve_submission(draft_v2.id, meeting2.id)
        platform.publish(draft_v2.id, date(2027, 6, 1))
        self.assertEqual(draft.status, DraftStatus.SUPERSEDED)
        self.assertEqual(draft_v2.status, DraftStatus.PUBLISHED)

    def test_only_submission_draft_can_publish(self):
        platform, actors = make_platform()
        clause = platform.add_clause("第4章", "术语")
        draft = platform.create_draft(clause.id, actors["research"].id, "定义脑机病房")
        with self.assertRaises(InvalidTransitionError):
            platform.publish(draft.id, EFFECTIVE_DAY)


if __name__ == "__main__":
    unittest.main()
