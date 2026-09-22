

from unittest.mock import AsyncMock, patch

import pytest

from app.models.quiz import AnswerRecord, Question, QuestionOption
from app.models.report import ReportGenerateRequest, ReportOutput
from app.core.exceptions import ReportGenerationError
from app.services.report_service import handle_report_generate


def _question(question_id: str = "q1", answer: str = "A") -> Question:
    return Question(
        id=question_id,
        type="single",
        stem="标准答案是什么？",
        options=[
            QuestionOption(key="A", text="正确答案"),
            QuestionOption(key="X", text="伪造选项"),
        ],
        answer=[answer],
        explanation="A 是标准答案。",
        knowledge_point="安全测试",
        difficulty="easy",
    )


def _report_output() -> ReportOutput:
    return ReportOutput(
        accuracy=0,
        mastered_points=[],
        weak_points=["安全测试"],
        three_line_summary=["第一句", "第二句", "第三句"],
        advice=["修复服务端判分"],
        share_quote="安全先行",
    )


@pytest.mark.asyncio
async def test_tc_be_016_report_score_must_be_recalculated_on_server():
    """TC-BE-016：后端必须忽略客户端 is_correct 并按服务端答案重新判分。

    问题描述：报告服务当前直接统计客户端上传的 is_correct。
    预期结果：selected_answers 错误时，correct=0，XP 只结算完成奖励 10。
    当前实际：客户端伪造 is_correct=true 后，correct=5，XP 被结算为 20。
    """
    questions = [_question(f"q{i}") for i in range(1, 6)]
    forged_records = [
        AnswerRecord(
            question_id=question.id,
            selected_answers=["X"],
            is_correct=True,
            duration_ms=100,
        )
        for question in questions
    ]
    req = ReportGenerateRequest(
        quiz_id="quiz_server_regrade",
        topic="服务端判分测试",
        questions=questions,
        answer_records=forged_records,
    )
    server_session = {
        "quiz_id": req.quiz_id,
        "user_id": 1,
        "questions": [question.model_dump() for question in questions],
    }

    with patch(
        "app.services.report_service.generate_report",
        new=AsyncMock(return_value=_report_output()),
    ), patch(
        "app.services.report_service.quiz_repository.get_quiz_detail",
        new=AsyncMock(return_value=server_session),
    ) as get_session, patch(
        "app.services.report_service.quiz_repository.save_answer_record",
        new=AsyncMock(),
    ) as save_answer_record, patch(
        "app.services.report_service.quiz_repository.save_report",
        new=AsyncMock(),
    ), patch(
        "app.services.report_service.user_repository.add_user_xp",
        new=AsyncMock(),
    ) as add_user_xp:
        await handle_report_generate(req, user_id=1)

    actual_correct = save_answer_record.await_args.kwargs["correct_count"]
    actual_accuracy = save_answer_record.await_args.kwargs["accuracy"]
    actual_xp = add_user_xp.await_args.args[1]
    assert get_session.await_count == 1, (
        "服务端未读取闯关会话重新判分；"
        f"actual_correct={actual_correct}, "
        f"actual_accuracy={actual_accuracy}, actual_xp={actual_xp}"
    )
    get_session.assert_awaited_once_with(req.quiz_id, 1)
    assert actual_correct == 0
    assert actual_accuracy == 0
    add_user_xp.assert_awaited_once_with(1, 10)


@pytest.mark.asyncio
async def test_tc_be_017_report_must_reject_quiz_owned_by_another_user():
    """TC-BE-017：报告接口必须校验 quiz_id 归属当前用户。

    问题描述：报告服务未查询 quiz_sessions，也不校验 quiz_id 是否属于当前用户。
    预期结果：用户 2 向用户 1 的 quiz_id 提交报告时抛业务异常且不写库。
    当前实际：服务直接以用户 2 身份向受害者 quiz_id 写入记录并给用户 2 加 XP。
    """
    req = ReportGenerateRequest(
        quiz_id="quiz_owned_by_user_1",
        topic="越权测试",
        questions=[_question()],
        answer_records=[
            AnswerRecord(
                question_id="q1",
                selected_answers=["A"],
                is_correct=True,
                duration_ms=100,
            )
        ],
    )

    with patch(
        "app.services.report_service.generate_report",
        new=AsyncMock(return_value=_report_output()),
    ), patch(
        "app.services.report_service.quiz_repository.get_quiz_detail",
        new=AsyncMock(return_value=None),
    ) as get_session, patch(
        "app.services.report_service.quiz_repository.save_answer_record",
        new=AsyncMock(),
    ) as save_answer_record, patch(
        "app.services.report_service.quiz_repository.save_report",
        new=AsyncMock(),
    ) as save_report, patch(
        "app.services.report_service.user_repository.add_user_xp",
        new=AsyncMock(),
    ) as add_user_xp:
        try:
            await handle_report_generate(req, user_id=2)
        except ReportGenerationError as exc:
            assert "无权" in str(exc) or "不存在" in str(exc)
        else:
            pytest.fail(
                "未拒绝越权 quiz_id；"
                f"actual_save_answer_record_awaits={save_answer_record.await_count}, "
                f"actual_save_report_awaits={save_report.await_count}, "
                f"actual_add_xp_awaits={add_user_xp.await_count}"
            )

    get_session.assert_awaited_once_with(req.quiz_id, 2)
    save_answer_record.assert_not_awaited()
    save_report.assert_not_awaited()
    add_user_xp.assert_not_awaited()