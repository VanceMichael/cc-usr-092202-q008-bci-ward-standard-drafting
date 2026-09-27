import unittest
from datetime import date
from pathlib import Path

from src.drafting import (
    CommentKind,
    Disposition,
    Ballot,
    DraftStatus,
    DraftingError,
)
from src.platform import DraftingPlatform, platform_from_context

ROLES = ["临床科室", "伦理委员会", "科研团队", "设备企业", "受试者管理人员"]
ALL_ATTENDEES = ["sec-01", "doc-01", "eth-01", "res-01", "ven-01", "sub-01"]


def make_platform() -> DraftingPlatform:
    platform = DraftingPlatform(roles=ROLES)
    platform.register_actor("sec-01", "王秘书", "秘书处", "标准工作组")
    platform.register_actor("doc-01", "陈医生", "临床科室", "试点医院甲")
    platform.register_actor("doc-02", "李医生", "临床科室", "试点医院乙")
    platform.register_actor("eth-01", "林委员", "伦理委员会", "试点医院甲")
    platform.register_actor("res-01", "赵研究员", "科研团队", "某高校脑机实验室")
    platform.register_actor("ven-01", "钱工程师", "设备企业", "某脑机设备公司")
    platform.register_actor("sub-01", "孙管理", "受试者管理人员", "试点医院乙")
    return platform


def push_to_submission(platform, draft_id, meeting_id, attendees=ALL_ATTENDEES, quorum=4):
    """完成一次合规会议(利益冲突声明齐全、达到法定人数、表决全票通过)并送审。"""
    platform.convene_meeting(meeting_id, date(2026, 7, 1), attendees, quorum)
    for actor_id in attendees:
        platform.declare_coi(meeting_id, actor_id)
    vote_id = f"VT-{meeting_id}"
    platform.open_vote(meeting_id, vote_id, draft_id)
    for actor_id in attendees:
        platform.cast_vote(meeting_id, vote_id, actor_id, Ballot.APPROVE)
    return platform.elevate_to_submission("sec-01", draft_id, meeting_id)


class LifecycleTest(unittest.TestCase):
    """征求意见 → 逐条处理 → 试点验证 → 会议表决 → 送审 → 发布留档的完整链路。"""

    def test_full_lifecycle_with_trace(self):
        platform = make_platform()
        platform.add_clause("CL-5.2", "第5章 病房分区", "信号屏蔽区设置", requires_pilot=True)
        platform.add_term("信号屏蔽区", "为降低环境电磁干扰而划设的专用区域", source="工作组讨论稿")
        platform.add_reference("REF-01", "T/BCI 001-2026", "脑机接口临床数据管理通则")
        platform.submit_proposal("doc-01", "CL-5.2", "PR-01",
                                 "病房应设置独立信号屏蔽区",
                                 "多家试点病区反馈环境电磁干扰导致采集中断")
        platform.create_draft("doc-01", "CL-5.2", "DR-01",
                              "脑机接口病房应设置独立信号屏蔽区。",
                              reference_ids=["REF-01"], proposal_id="PR-01")
        platform.open_for_comment("doc-01", "DR-01")
        platform.submit_comment("res-01", "DR-01", "CM-01", "建议明确屏蔽区面积下限")
        platform.submit_comment("ven-01", "DR-01", "CM-02",
                                "反对:屏蔽区建设成本过高,中小机构难以承担",
                                kind=CommentKind.OBJECTION)
        platform.process_comment("sec-01", "CM-01", Disposition.ADOPTED,
                                 "采纳,补充面积下限",
                                 revised_text="脑机接口病房应设置独立信号屏蔽区,面积不应小于20平方米。")
        platform.process_comment("sec-01", "CM-02", Disposition.REJECTED,
                                 "试点证据显示屏蔽区显著降低信号中断,成本可由多病区共用摊薄")
        platform.attach_evidence("res-01", "CL-5.2", "EV-2026-001",
                             "试点病区A(已脱敏)", "2026-03至2026-05",
                             "设置屏蔽区后信号中断由每周5起降至每周1起", deidentified=True)
        push_to_submission(platform, "DR-01", "MT-01")
        trace = platform.publish("sec-01", "DR-01", date(2026, 8, 1), date(2026, 10, 1))

        self.assertEqual(platform.drafts["DR-01"].status, DraftStatus.PUBLISHED)
        self.assertEqual(trace.proposer_id, "doc-01")
        self.assertEqual(trace.proposal_id, "PR-01")
        self.assertEqual(trace.evidence_ids, ["EV-2026-001"])
        self.assertEqual(len(trace.objections), 1)
        self.assertEqual(trace.objections[0].disposition, Disposition.REJECTED)
        self.assertIn("摊薄", trace.objections[0].reason)
        self.assertEqual(trace.comment_summary["adopted"], 1)
        self.assertEqual(trace.comment_summary["rejected"], 1)
        self.assertEqual(trace.meeting_id, "MT-01")
        self.assertEqual(trace.effective_date, date(2026, 10, 1))
        self.assertEqual(platform.trace_requirement("CL-5.2").draft_id, "DR-01")


class ParallelDraftTest(unittest.TestCase):
    def test_parallel_drafts_and_supersede_on_publish(self):
        platform = make_platform()
        platform.add_clause("CL-8.1", "第8章 数据保存", "保存期限")
        platform.create_draft("doc-01", "CL-8.1", "DR-A", "脑机数据保存期限不少于15年。")
        platform.create_draft("res-01", "CL-8.1", "DR-B", "脑机数据保存期限不少于30年。")
        # 并行草案可分别进入征求意见
        platform.open_for_comment("doc-01", "DR-A")
        platform.open_for_comment("res-01", "DR-B")
        push_to_submission(platform, "DR-A", "MT-A")
        push_to_submission(platform, "DR-B", "MT-B")
        platform.publish("sec-01", "DR-A", date(2026, 8, 1), date(2026, 9, 1))
        self.assertEqual(platform.trace_requirement("CL-8.1").draft_id, "DR-A")
        # 同一条款同一时刻仅一份生效要求,新发布替代旧版且旧版留档可查
        platform.publish("sec-01", "DR-B", date(2026, 9, 1), date(2026, 10, 1))
        self.assertEqual(platform.drafts["DR-A"].status, DraftStatus.SUPERSEDED)
        self.assertEqual(platform.trace_requirement("CL-8.1").draft_id, "DR-B")
        self.assertEqual(len(platform.archive), 2)


class SubmissionGateTest(unittest.TestCase):
    def setUp(self):
        self.platform = make_platform()
        self.platform.add_clause("CL-6.1", "第6章 人员配置", "专职数据管理员")
        self.platform.create_draft("res-01", "CL-6.1", "DR-02",
                                   "病房应配备至少1名专职数据管理员。")
        self.platform.open_for_comment("res-01", "DR-02")

    def test_submission_requires_quorum(self):
        platform = self.platform
        platform.convene_meeting("MT-Q", date(2026, 7, 12), ["sec-01", "doc-01", "res-01"], quorum=4)
        for actor_id in ["sec-01", "doc-01", "res-01"]:
            platform.declare_coi("MT-Q", actor_id)
        platform.open_vote("MT-Q", "VT-Q", "DR-02")
        for actor_id in ["sec-01", "doc-01", "res-01"]:
            platform.cast_vote("MT-Q", "VT-Q", actor_id, Ballot.APPROVE)
        with self.assertRaisesRegex(DraftingError, "法定人数"):
            platform.elevate_to_submission("sec-01", "DR-02", "MT-Q")

    def test_submission_requires_complete_coi(self):
        platform = self.platform
        attendees = ["sec-01", "doc-01", "eth-01", "res-01"]
        platform.convene_meeting("MT-C", date(2026, 7, 19), attendees, quorum=4)
        for actor_id in ["sec-01", "doc-01", "eth-01"]:
            platform.declare_coi("MT-C", actor_id)
        platform.open_vote("MT-C", "VT-C", "DR-02")
        for actor_id in attendees:
            platform.cast_vote("MT-C", "VT-C", actor_id, Ballot.APPROVE)
        with self.assertRaisesRegex(DraftingError, "利益冲突"):
            platform.elevate_to_submission("sec-01", "DR-02", "MT-C")
        platform.declare_coi("MT-C", "res-01")
        platform.elevate_to_submission("sec-01", "DR-02", "MT-C")
        self.assertEqual(platform.drafts["DR-02"].status, DraftStatus.SUBMISSION)

    def test_unprocessed_comment_blocks_submission(self):
        platform = self.platform
        platform.submit_comment("sub-01", "DR-02", "CM-09", "建议明确数据管理员的资质要求")
        platform.convene_meeting("MT-U", date(2026, 7, 20), ALL_ATTENDEES, quorum=4)
        for actor_id in ALL_ATTENDEES:
            platform.declare_coi("MT-U", actor_id)
        platform.open_vote("MT-U", "VT-U", "DR-02")
        for actor_id in ALL_ATTENDEES:
            platform.cast_vote("MT-U", "VT-U", actor_id, Ballot.APPROVE)
        with self.assertRaisesRegex(DraftingError, "未处理意见"):
            platform.elevate_to_submission("sec-01", "DR-02", "MT-U")
        platform.process_comment("res-01", "CM-09", Disposition.PARTIALLY_ADOPTED,
                                 "资质要求另立条款,本条款仅明确配置数量")
        platform.elevate_to_submission("sec-01", "DR-02", "MT-U")
        self.assertEqual(platform.drafts["DR-02"].status, DraftStatus.SUBMISSION)


class CommentRuleTest(unittest.TestCase):
    def test_comment_stage_and_processing_rules(self):
        platform = make_platform()
        platform.add_clause("CL-9.1", "第9章 患者筛选", "知情同意")
        platform.create_draft("eth-01", "CL-9.1", "DR-C", "入选患者应签署专用知情同意书。")
        with self.assertRaisesRegex(DraftingError, "征求意见"):
            platform.submit_comment("res-01", "DR-C", "CM-1", "草案尚未公开征求意见")
        platform.open_for_comment("eth-01", "DR-C")
        platform.submit_comment("ven-01", "DR-C", "CM-1", "建议补充知情同意书模板")
        with self.assertRaisesRegex(DraftingError, "理由"):
            platform.process_comment("sec-01", "CM-1", Disposition.REJECTED, "")
        with self.assertRaisesRegex(DraftingError, "作者或秘书处"):
            platform.process_comment("ven-01", "CM-1", Disposition.ADOPTED, "自行处理")
        platform.process_comment("sec-01", "CM-1", Disposition.ADOPTED, "采纳,附录补充模板")
        with self.assertRaisesRegex(DraftingError, "重复处理"):
            platform.process_comment("sec-01", "CM-1", Disposition.REJECTED, "再次处理")


class PilotEvidenceTest(unittest.TestCase):
    def test_evidence_must_be_deidentified_and_present(self):
        platform = make_platform()
        platform.add_clause("CL-5.2", "第5章 病房分区", "信号屏蔽区设置", requires_pilot=True)
        with self.assertRaisesRegex(DraftingError, "脱敏"):
            platform.attach_evidence("res-01", "CL-5.2", "EV-BAD", "某病区",
                                     "2026-01", "含可识别信息的原始记录", deidentified=False)
        platform.create_draft("doc-01", "CL-5.2", "DR-E", "应设置独立信号屏蔽区。")
        platform.open_for_comment("doc-01", "DR-E")
        platform.convene_meeting("MT-E", date(2026, 7, 5), ["sec-01", "doc-01", "eth-01", "res-01"], quorum=4)
        for actor_id in ["sec-01", "doc-01", "eth-01", "res-01"]:
            platform.declare_coi("MT-E", actor_id)
        platform.open_vote("MT-E", "VT-E", "DR-E")
        for actor_id in ["sec-01", "doc-01", "eth-01", "res-01"]:
            platform.cast_vote("MT-E", "VT-E", actor_id, Ballot.APPROVE)
        with self.assertRaisesRegex(DraftingError, "试点"):
            platform.elevate_to_submission("sec-01", "DR-E", "MT-E")
        platform.attach_evidence("res-01", "CL-5.2", "EV-OK", "试点病区A(已脱敏)",
                                 "2026-03至2026-05", "信号中断显著下降", deidentified=True)
        platform.elevate_to_submission("sec-01", "DR-E", "MT-E")
        self.assertEqual(platform.drafts["DR-E"].status, DraftStatus.SUBMISSION)


class VoteRuleTest(unittest.TestCase):
    def test_ballot_restrictions_and_failed_vote_returns_draft(self):
        platform = make_platform()
        platform.add_clause("CL-9.1", "第9章 患者筛选", "知情同意")
        platform.create_draft("eth-01", "CL-9.1", "DR-V", "入选患者应签署专用知情同意书。")
        platform.open_for_comment("eth-01", "DR-V")
        attendees = ["sec-01", "doc-01", "eth-01", "ven-01"]
        platform.convene_meeting("MT-V", date(2026, 7, 20), attendees, quorum=4)
        for actor_id in attendees:
            platform.declare_coi("MT-V", actor_id)
        platform.open_vote("MT-V", "VT-V", "DR-V")
        with self.assertRaisesRegex(DraftingError, "出席者"):
            platform.cast_vote("MT-V", "VT-V", "res-01", Ballot.APPROVE)
        platform.cast_vote("MT-V", "VT-V", "sec-01", Ballot.APPROVE)
        with self.assertRaisesRegex(DraftingError, "重复表决"):
            platform.cast_vote("MT-V", "VT-V", "sec-01", Ballot.APPROVE)
        platform.cast_vote("MT-V", "VT-V", "doc-01", Ballot.APPROVE)
        platform.cast_vote("MT-V", "VT-V", "eth-01", Ballot.REJECT)
        platform.cast_vote("MT-V", "VT-V", "ven-01", Ballot.REJECT)
        # 2/4 同意,未达到 3/4,草案退回
        with self.assertRaisesRegex(DraftingError, "表决未通过"):
            platform.elevate_to_submission("sec-01", "DR-V", "MT-V")
        self.assertEqual(platform.drafts["DR-V"].status, DraftStatus.RETURNED)
        # 退回后重新征求意见并再次上会
        platform.open_for_comment("eth-01", "DR-V")
        push_to_submission(platform, "DR-V", "MT-V2", attendees=attendees)
        self.assertEqual(platform.drafts["DR-V"].status, DraftStatus.SUBMISSION)


class PublishRuleTest(unittest.TestCase):
    def test_publish_restrictions(self):
        platform = make_platform()
        platform.add_clause("CL-10.1", "第10章 术语和定义", "脑机接口病房")
        platform.create_draft("sec-01", "CL-10.1", "DR-P",
                              "脑机接口病房:开展脑机接口临床应用的专用病房。")
        with self.assertRaisesRegex(DraftingError, "送审稿"):
            platform.publish("sec-01", "DR-P", date(2026, 9, 1), date(2026, 10, 1))
        platform.open_for_comment("sec-01", "DR-P")
        push_to_submission(platform, "DR-P", "MT-P")
        with self.assertRaisesRegex(DraftingError, "秘书处"):
            platform.publish("doc-01", "DR-P", date(2026, 9, 1), date(2026, 10, 1))
        with self.assertRaisesRegex(DraftingError, "生效日期"):
            platform.publish("sec-01", "DR-P", date(2026, 9, 1), date(2026, 8, 1))
        platform.publish("sec-01", "DR-P", date(2026, 9, 1), date(2026, 10, 1))
        self.assertEqual(platform.drafts["DR-P"].status, DraftStatus.PUBLISHED)


class WithdrawalTest(unittest.TestCase):
    def test_reference_withdrawal_flags_affected_content(self):
        platform = make_platform()
        platform.add_clause("CL-11.1", "第11章 设备管理", "设备巡检")
        platform.add_reference("REF-X", "T/BCI 002-2025", "脑机设备巡检规程")
        platform.create_draft("ven-01", "CL-11.1", "DR-R1",
                              "设备巡检应按 T/BCI 002 执行。", reference_ids=["REF-X"])
        platform.create_draft("doc-01", "CL-11.1", "DR-R2",
                              "巡检记录保存不少于5年。", reference_ids=["REF-X"])
        platform.open_for_comment("ven-01", "DR-R1")
        push_to_submission(platform, "DR-R1", "MT-R")
        platform.publish("sec-01", "DR-R1", date(2026, 8, 1), date(2026, 9, 1))

        affected = platform.withdraw_reference("sec-01", "REF-X")
        kinds = {(item.kind, item.label) for item in affected}
        self.assertIn(("draft", "DR-R2"), kinds)
        self.assertIn(("published", "DR-R1"), kinds)
        self.assertEqual(platform.drafts["DR-R2"].withdrawal_flags, ["REF-X"])
        self.assertEqual(platform.trace_requirement("CL-11.1").withdrawal_flags, ["REF-X"])
        with self.assertRaisesRegex(DraftingError, "已撤回"):
            platform.create_draft("doc-01", "CL-11.1", "DR-R3",
                                  "新草案仍引用已撤回标准。", reference_ids=["REF-X"])


class VisibilityTest(unittest.TestCase):
    def test_unpublished_drafts_restricted_by_role(self):
        platform = make_platform()
        platform.add_clause("CL-12.1", "第12章 数据安全", "访问控制")
        platform.create_draft("doc-01", "CL-12.1", "DR-W", "脑机数据访问应分级授权。")
        # 未公开草案:作者本人、同角色成员与秘书处可见,其他角色不可见
        self.assertTrue(platform.can_view("doc-01", "DR-W"))
        self.assertTrue(platform.can_view("doc-02", "DR-W"))
        self.assertTrue(platform.can_view("sec-01", "DR-W"))
        self.assertFalse(platform.can_view("ven-01", "DR-W"))
        self.assertFalse(platform.can_view("eth-01", "DR-W"))
        self.assertEqual([d.draft_id for d in platform.visible_drafts("ven-01")], [])
        # 进入征求意见后向全体注册角色公开
        platform.open_for_comment("doc-01", "DR-W")
        self.assertTrue(platform.can_view("ven-01", "DR-W"))

    def test_custom_visible_roles(self):
        platform = make_platform()
        platform.add_clause("CL-12.2", "第12章 数据安全", "伦理审查")
        platform.create_draft("doc-01", "CL-12.2", "DR-X", "数据使用应经伦理审查。",
                              visible_roles={"伦理委员会"})
        self.assertTrue(platform.can_view("eth-01", "DR-X"))
        self.assertFalse(platform.can_view("res-01", "DR-X"))
        with self.assertRaisesRegex(DraftingError, "未知协作角色"):
            platform.create_draft("doc-01", "CL-12.2", "DR-Y", "文本。",
                                  visible_roles={"患者家属"})


class ContextTest(unittest.TestCase):
    def test_platform_from_shared_context(self):
        platform = platform_from_context(Path("fixtures/context.json"))
        for role in ROLES:
            self.assertIn(role, platform.roles)
        platform.register_actor("a-1", "某医生", "临床科室", "某医院")
        with self.assertRaisesRegex(DraftingError, "未知协作角色"):
            platform.register_actor("a-2", "某人", "患者家属", "某病区")


if __name__ == "__main__":
    unittest.main()
