# -*- coding: utf-8 -*-
"""健康检查、框架行为与响应模型基础验收。"""
from __future__ import annotations

from app.core.security import check_content
from app.models.quiz import AnswerRecord
from app.services.scoring_service import compute_score_summary
from assertions import assert_success
from conftest import CustomClient


def test_TC001_health_check_returns_ok():
    with CustomClient() as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_TC002_openapi_document_is_exposed():
    with CustomClient() as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    for path in (
        "/api/v1/health",
        "/api/v1/quiz/generate",
        "/api/v1/quiz/generate/async",
        "/api/v1/report/generate",
        "/api/v1/user/profile",
        "/api/v1/knowledge/documents",
    ):
        assert path in paths


def test_TC003_cors_allows_configured_origin():
    with CustomClient() as client:
        response = client.options(
            "/api/v1/health",
            headers={"Origin": "http://localhost:10086", "Access-Control-Request-Method": "GET"},
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:10086"


def test_TC010_sensitive_word_filter_blocks_all_configured_keywords():
    blocked = ["暴力", "色情", "赌博", "毒品", "自杀", "恐怖", "炸弹", "爆炸", "入侵", "黑客攻击", "武器"]
    assert [check_content(word) for word in blocked] == [False] * len(blocked)
    assert check_content("FastAPI 与 Pydantic 学习") is True


def test_TC020_scoring_service_calculates_accuracy_and_duration():
    records = [
        AnswerRecord(question_id="q1", selected_answers=["A"], is_correct=True, duration_ms=1000),
        AnswerRecord(question_id="q2", selected_answers=["B"], is_correct=False, duration_ms=3000),
        AnswerRecord(question_id="q3", selected_answers=["A"], is_correct=True, duration_ms=2000),
    ]
    result = compute_score_summary(records)
    assert result == {
        "total": 3,
        "correct": 2,
        "wrong": 1,
        "accuracy": 67,
        "avg_duration_ms": 2000,
    }


def test_TC021_scoring_service_handles_empty_answer_records():
    assert compute_score_summary([]) == {
        "total": 0,
        "correct": 0,
        "wrong": 0,
        "accuracy": 0,
        "avg_duration_ms": 0,
    }

