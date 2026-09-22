# -*- coding: utf-8 -*-
"""报告接口安全缺陷回归验收。"""
from __future__ import annotations

import app.services.report_service as report_service
from app.models.report import ReportOutput
from assertions import assert_error, assert_success
from conftest import CustomClient, auth_headers, make_quiz_output


def make_report_output(accuracy: int = 0) -> ReportOutput:
    return ReportOutput(
        accuracy=accuracy,
        mastered_points=[],
        weak_points=["安全测试"],
        three_line_summary=["第一句", "第二句", "第三句"],
        advice=["修复服务端判分"],
        share_quote="安全先行",
    )


def sample_report_request(question_count: int = 5) -> dict:
    quiz = make_quiz_output(question_count)
    records = [
        {
            "question_id": question.id,
            "selected_answers": ["B"],
            "is_correct": True,
            "duration_ms": 100,
        }
        for question in quiz.questions
    ]
    return {
        "quiz_id": "quiz_server_regrade",
        "topic": "服务端判分测试",
        "questions": [question.model_dump() for question in quiz.questions],
        "answer_records": records,
    }


def test_TC050_report_score_must_be_recalculated_on_server(monkeypatch):
    """客户端伪造 is_correct 时，后端必须按服务端标准答案重新判分。"""
    payload = sample_report_request()
    captured = {}

    async def get_quiz_detail(quiz_id, user_id):
        captured["session_lookup"] = (quiz_id, user_id)
        return {
            "quiz_id": quiz_id,
            "user_id": user_id,
            "title": payload["topic"],
            "questions": payload["questions"],
        }

    async def success_report(**kwargs):
        captured["report_answer_records"] = kwargs["answer_records"]
        return make_report_output(accuracy=99)

    async def save_answer_record(**kwargs):
        captured["answer_record"] = kwargs

    async def save_report(**kwargs):
        captured["report"] = kwargs

    async def add_user_xp(user_id, xp_gain):
        captured["xp"] = (user_id, xp_gain)

    monkeypatch.setattr(report_service, "generate_report", success_report)
    monkeypatch.setattr(report_service.quiz_repository, "get_quiz_detail", get_quiz_detail)
    monkeypatch.setattr(report_service.quiz_repository, "save_answer_record", save_answer_record)
    monkeypatch.setattr(report_service.quiz_repository, "save_report", save_report)
    monkeypatch.setattr(report_service.user_repository, "add_user_xp", add_user_xp)

    with CustomClient() as client:
        data = assert_success(
            client.post(
                "/api/v1/report/generate",
                headers=auth_headers(5001),
                json=payload,
            )
        )

    assert captured["session_lookup"] == (payload["quiz_id"], 5001)
    assert all(record.is_correct is False for record in captured["report_answer_records"])
    assert captured["answer_record"]["correct_count"] == 0
    assert captured["answer_record"]["accuracy"] == 0
    assert captured["xp"] == (5001, 10)
    assert data["accuracy"] == 0


def test_TC051_report_must_reject_quiz_owned_by_another_user(monkeypatch):
    """报告接口必须校验 quiz_id 归属当前用户，越权时不得调用模型或写库。"""
    payload = sample_report_request(question_count=1)
    payload["quiz_id"] = "quiz_owned_by_user_1"
    captured = {"session_lookups": []}

    async def missing_detail(quiz_id, user_id):
        captured["session_lookups"].append((quiz_id, user_id))
        return None

    async def forbidden_report(**kwargs):
        raise AssertionError("越权请求不应调用报告模型")

    async def forbidden_save_answer_record(**kwargs):
        raise AssertionError("越权请求不应保存答题记录")

    async def forbidden_save_report(**kwargs):
        raise AssertionError("越权请求不应保存报告")

    async def forbidden_add_user_xp(user_id, xp_gain):
        raise AssertionError("越权请求不应增加经验值")

    monkeypatch.setattr(report_service, "generate_report", forbidden_report)
    monkeypatch.setattr(report_service.quiz_repository, "get_quiz_detail", missing_detail)
    monkeypatch.setattr(report_service.quiz_repository, "save_answer_record", forbidden_save_answer_record)
    monkeypatch.setattr(report_service.quiz_repository, "save_report", forbidden_save_report)
    monkeypatch.setattr(report_service.user_repository, "add_user_xp", forbidden_add_user_xp)

    with CustomClient() as client:
        body = assert_error(
            client.post(
                "/api/v1/report/generate",
                headers=auth_headers(5002),
                json=payload,
            ),
            500,
            5002,
        )

    assert captured["session_lookups"] == [(payload["quiz_id"], 5002)]
    assert "无权" in body["message"] or "不存在" in body["message"]
