"""协同编制平台的领域异常。"""


class DraftingError(Exception):
    """平台领域异常的基类。"""


class DraftVisibilityError(DraftingError):
    """未公开草案对当前角色不可见。"""


class InvalidTransitionError(DraftingError):
    """草案或记录的状态不允许当前操作。"""


class MeetingNotReadyError(DraftingError):
    """会议未完成利益冲突声明或未达到法定人数。"""


class UnresolvedFeedbackError(DraftingError):
    """存在未逐条处理的意见或未了结的反对意见。"""


class EvidenceNotVerifiedError(DraftingError):
    """条款要求试点验证但缺少验证通过的证据。"""


class WithdrawnReferenceError(DraftingError):
    """条款引用的规范性文件已撤回且尚未处理。"""


class VoteThresholdError(DraftingError):
    """表决未达到通过门槛。"""
