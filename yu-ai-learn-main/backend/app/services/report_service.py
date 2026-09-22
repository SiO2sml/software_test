"""报告服务"""

from typing import Any

import structlog

from app.core.exceptions import ReportGenerationError
from app.llm.report_chain import generate_report
from app.models.quiz import AnswerRecord, Question
from app.models.report import ReportGenerateRequest, ReportGenerateResponse
from app.services.scoring_service import compute_score_summary
from app.repositories import quiz_repository, user_repository

logger = structlog.get_logger()


def _parse_session_questions(raw_questions: Any) -> list[Question]:
    """解析服务端保存的题目，拒绝空题目或格式被篡改的数据。"""
    try:
        questions = [Question.model_validate(item) for item in raw_questions or []]
    except Exception as e:
        raise ReportGenerationError("闯关题目数据异常，请重新生成题目") from e

    if not questions:
        raise ReportGenerationError("闯关题目数据不存在，请重新生成题目")

    question_ids = [question.id for question in questions]
    if len(question_ids) != len(set(question_ids)):
        raise ReportGenerationError("闯关题目数据异常，请重新生成题目")

    return questions


def _rescore_answer_records(
    questions: list[Question],
    answer_records: list[AnswerRecord],
) -> list[AnswerRecord]:
    """以服务端保存的标准答案重新判分，忽略客户端提交的 is_correct。"""
    if len(answer_records) != len(questions):
        raise ReportGenerationError("答题记录数量与题目数量不一致")

    question_map = {question.id: question for question in questions}
    seen_question_ids: set[str] = set()
    corrected_records: list[AnswerRecord] = []

    for record in answer_records:
        question = question_map.get(record.question_id)
        if question is None:
            raise ReportGenerationError("答题记录包含不存在的题目")
        if record.question_id in seen_question_ids:
            raise ReportGenerationError("答题记录包含重复题目")
        seen_question_ids.add(record.question_id)

        option_keys = {option.key for option in question.options}
        selected_keys = record.selected_answers
        if len(selected_keys) != len(set(selected_keys)):
            raise ReportGenerationError("答题记录包含重复选项")
        if any(key not in option_keys for key in selected_keys):
            raise ReportGenerationError("答题记录包含无效选项")

        is_correct = set(selected_keys) == set(question.answer)
        corrected_records.append(record.model_copy(update={"is_correct": is_correct}))

    return corrected_records


async def _load_owned_quiz_session(quiz_id: str, user_id: int) -> dict:
    """加载当前用户拥有的闯关会话，并在生成报告前完成权限检查。"""
    session = await quiz_repository.get_quiz_detail(quiz_id, user_id)
    if session is None:
        raise ReportGenerationError("闯关记录不存在或无权访问")
    if session.get("answer_records") is not None or session.get("report") is not None:
        raise ReportGenerationError("该闯关已生成报告，请勿重复提交")
    return session


async def handle_report_generate(
    req: ReportGenerateRequest,
    user_id: int,
) -> ReportGenerateResponse:
    # 先校验会话归属，避免越权请求消耗大模型资源。
    session = await _load_owned_quiz_session(req.quiz_id, user_id)
    server_questions = _parse_session_questions(session.get("questions"))
    corrected_records = _rescore_answer_records(server_questions, req.answer_records)
    score_summary = compute_score_summary(corrected_records)

    try:
        report_output = await generate_report(
            topic=session.get("title") or req.topic,
            questions=server_questions,
            answer_records=corrected_records,
            score_summary=score_summary,
        )
    except Exception as e:
        logger.error("report_generation_failed", error=str(e))
        raise ReportGenerationError(f"报告生成失败：{e}") from e

    # 报告中的掌握度以服务端重判结果为准，避免模型输出被客户端数据带偏。
    report_output = report_output.model_copy(
        update={"accuracy": score_summary["accuracy"]}
    )

    try:
        # 保存服务端重判后的答题记录
        await quiz_repository.save_answer_record(
            quiz_id=req.quiz_id,
            user_id=user_id,
            records_json=[record.model_dump() for record in corrected_records],
            total_questions=score_summary["total"],
            correct_count=score_summary["correct"],
            accuracy=score_summary["accuracy"],
        )
        # 保存报告
        await quiz_repository.save_report(
            quiz_id=req.quiz_id,
            user_id=user_id,
            report_json=report_output.model_dump(),
        )
        # 累加经验值：完成闯关 +10，每答对一题 +2
        xp_gain = 10 + score_summary["correct"] * 2
        await user_repository.add_user_xp(user_id, xp_gain)
    except Exception as e:
        logger.error("report_persist_failed", error=str(e))

    return ReportGenerateResponse(
        accuracy=score_summary["accuracy"],
        mastered_points=report_output.mastered_points,
        weak_points=report_output.weak_points,
        three_line_summary=report_output.three_line_summary,
        advice=report_output.advice,
        share_quote=report_output.share_quote,
    )
