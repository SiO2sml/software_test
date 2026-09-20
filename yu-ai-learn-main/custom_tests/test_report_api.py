# -*- coding: utf-8 -*-
"""AI复盘报告接口验收。"""
from __future__ import annotations

import pytest

import app.services.report_service as report_service
from assertions import assert_error, assert_success, assert_validation_error
from conftest import CustomClient, auth_headers, make_quiz_output


def sample_request(question_count: int = 2):
    quiz = make_quiz_output(question_count)
    records = [
        {
            "question_id": q.id,
            "selected_answers": q.answer if index == 0 else ["B"],
            "is_correct": index == 0,
            "duration_ms": 1000 * (index + 1),
        }
        for index, q in enumerate(quiz.questions)
    ]
    return {
        "quiz_id": "quiz_report01",
        "topic": quiz.title,
        "questions": [q.model_dump() for q in quiz.questions],
        "answer_records": records,
    }


@pytest.fixture
def patch_report_success(monkeypatch):
    async def success_report(**kwargs):
        from app.models.report import ReportOutput
        return ReportOutput(
            accuracy=50,
            mastered_points=["知识点1"],
            weak_points=["知识点2"],
            three_line_summary=["第一句", "第二句", "第三句"],
            advice=["复习知识点2"],
            share_quote="每天进步一点点。",
        )

    monkeypatch.setattr(report_service, "generate_report", success_report)


def test_TC030_report_generate_validates_required_payload():
    with CustomClient() as client:
        response = client.post("/api/v1/report/generate", json={"quiz_id": "q"})
        assert_validation_error(response)

        invalid = sample_request()
        invalid["answer_records"][0]["duration_ms"] = -1
        response = client.post("/api/v1/report/generate", json=invalid)
        assert_validation_error(response)


def test_TC031_report_generate_llm_failure_returns_report_error(monkeypatch):
    async def failing_report(**kwargs):
        raise RuntimeError("报告模型失败")

    monkeypatch.setattr(report_service, "generate_report", failing_report)
    with CustomClient() as client:
        body = assert_error(
            client.post("/api/v1/report/generate", json=sample_request()), 500, 5002
        )
    assert "报告生成失败" in body["message"]


def test_TC032_report_generate_returns_full_report(patch_report_success):
    with CustomClient() as client:
        data = assert_success(client.post("/api/v1/report/generate", json=sample_request()))
    assert data["accuracy"] == 50
    assert data["mastered_points"] == ["知识点1"]
    assert data["weak_points"] == ["知识点2"]
    assert len(data["three_line_summary"]) == 3
    assert data["share_quote"]


def test_TC033_report_generate_with_invalid_login_stays_anonymous(patch_report_success):
    """可选鉴权接口应继续支持游客；无效 token 不能阻断学习流程。"""
    with CustomClient() as client:
        data = assert_success(
            client.post(
                "/api/v1/report/generate",
                headers={"Authorization": "Bearer invalid-token"},
                json=sample_request(),
            )
        )
    assert data["accuracy"] == 50


def test_TC034_report_generate_supports_empty_answer_records(patch_report_success):
    payload = sample_request()
    payload["answer_records"] = []
    with CustomClient() as client:
        data = assert_success(client.post("/api/v1/report/generate", json=payload))
    assert data["accuracy"] == 50
