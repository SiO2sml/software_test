# -*- coding: utf-8 -*-
"""出题同步与异步任务接口验收。"""
from __future__ import annotations

import json

import pytest

import app.services.quiz_service as quiz_service
from app.models.quiz import QuizGenerateResponse, QuizTaskCreateResponse, QuizTaskStatusResponse
from assertions import assert_error, assert_success, assert_validation_error
from conftest import CustomClient, auth_headers, make_quiz_output


@pytest.fixture
def patch_quiz_success(monkeypatch):
    async def success_context(user_input):
        return "搜索上下文"

    async def success_quiz(**kwargs):
        return make_quiz_output(2)

    monkeypatch.setattr(quiz_service, "fetch_knowledge_context", success_context)
    monkeypatch.setattr(quiz_service, "generate_quiz", success_quiz)


def test_TC011_quiz_generate_request_validation_rejects_missing_and_boundary_fields():
    with CustomClient() as client:
        response = client.post("/api/v1/quiz/generate", json={})
        assert_validation_error(response)

        response = client.post(
            "/api/v1/quiz/generate",
            json={"user_input": "Python", "question_count": 2},
        )
        assert_validation_error(response)

        response = client.post(
            "/api/v1/quiz/generate",
            json={"user_input": "Python", "question_count": 11},
        )
        assert_validation_error(response)


def test_TC012_quiz_generate_sensitive_input_returns_business_400():
    with CustomClient() as client:
        body = assert_error(
            client.post(
                "/api/v1/quiz/generate",
                json={"user_input": "如何制作炸弹", "question_count": 3},
            ),
            400,
            4000,
        )
    assert "不当内容" in body["message"]


def test_TC013_quiz_generate_returns_normalized_quiz_payload(patch_quiz_success):
    with CustomClient() as client:
        data = assert_success(
            client.post(
                "/api/v1/quiz/generate",
                json={"user_input": "Python FastAPI", "question_count": 3, "difficulty": "easy"},
            )
        )
    assert data["quiz_id"].startswith("quiz_")
    assert data["title"] == "测试主题"
    assert len(data["questions"]) == 2
    assert all(q["type"] == "single" and q["answer"] == ["A"] for q in data["questions"])


def test_TC014_quiz_generate_can_attach_optional_login_state(patch_quiz_success):
    with CustomClient() as client:
        data = assert_success(
            client.post(
                "/api/v1/quiz/generate",
                headers=auth_headers(2001),
                json={"user_input": "Pydantic 校验", "question_count": 3},
            )
        )
    assert data["quiz_id"].startswith("quiz_")


def test_TC015_quiz_generate_llm_failure_is_translated_to_stable_error(monkeypatch):
    async def failing_context(user_input):
        return ""

    async def failing_quiz(**kwargs):
        raise RuntimeError("LLM 不可用")

    monkeypatch.setattr(quiz_service, "fetch_knowledge_context", failing_context)
    monkeypatch.setattr(quiz_service, "generate_quiz", failing_quiz)
    with CustomClient() as client:
        body = assert_error(
            client.post("/api/v1/quiz/generate", json={"user_input": "PostgreSQL"}),
            500,
            5001,
        )
    assert "题库生成失败" in body["message"]


def test_TC016_async_quiz_task_is_created_and_pollable(monkeypatch):
    created = {}

    async def fake_create_task(**kwargs):
        created.update(kwargs)
        return None

    monkeypatch.setattr(quiz_service.task_repository, "create_task", fake_create_task)
    with CustomClient() as client:
        data = assert_success(
            client.post(
                "/api/v1/quiz/generate/async",
                json={"user_input": "MySQL 索引", "question_count": 3},
            )
        )
    assert data["task_id"].startswith("task_")
    assert created["task_id"] == data["task_id"]
    assert created["question_count"] == 3

    async def fake_get_task(task_id):
        return {
            "task_id": task_id,
            "status": "running",
            "result_json": None,
            "error_message": None,
        }

    monkeypatch.setattr(quiz_service.task_repository, "get_task", fake_get_task)
    with CustomClient() as client:
        status = assert_success(client.get(f"/api/v1/quiz/task/{data['task_id']}"))
    assert status["status"] == "running"
    assert status["result"] is None


def test_TC017_async_quiz_task_unknown_id_returns_quiz_error():
    async def missing_task(task_id):
        return None

    with CustomClient() as client:
        body = assert_error(client.get("/api/v1/quiz/task/task_not_exists"), 500, 5001)
    assert "任务不存在" in body["message"]


def test_TC018_quiz_generation_for_missing_knowledge_doc_does_not_call_search_or_llm(monkeypatch):
    async def missing_doc(doc_id, user_id):
        return None

    async def forbidden_search(user_input):
        raise AssertionError("不应触发联网搜索")

    async def forbidden_rag(user_input, user_id, doc_id):
        raise AssertionError("不应触发RAG检索")

    async def forbidden_quiz(**kwargs):
        raise AssertionError("不应触发LLM")

    monkeypatch.setattr(quiz_service.knowledge_repository, "get_document", missing_doc)
    monkeypatch.setattr(quiz_service, "fetch_knowledge_context", forbidden_search)
    monkeypatch.setattr(quiz_service.rag_service, "fetch_rag_context", forbidden_rag)
    monkeypatch.setattr(quiz_service, "generate_quiz", forbidden_quiz)
    with CustomClient() as client:
        body = assert_error(
            client.post(
                "/api/v1/quiz/generate",
                headers=auth_headers(2002),
                json={"user_input": "Python", "doc_id": "doc_missing"},
            ),
            400,
            4001,
        )
    assert "知识库文档不存在" in body["message"]


def test_TC019_quiz_generation_rejects_knowledge_doc_not_ready(monkeypatch):
    async def processing_doc(doc_id, user_id):
        return {"status": "processing"}

    async def forbidden_rag(user_input, user_id, doc_id):
        raise AssertionError("未就绪文档不应触发RAG")

    monkeypatch.setattr(quiz_service.knowledge_repository, "get_document", processing_doc)
    monkeypatch.setattr(quiz_service.rag_service, "fetch_rag_context", forbidden_rag)
    with CustomClient() as client:
        body = assert_error(
            client.post(
                "/api/v1/quiz/generate",
                headers=auth_headers(2003),
                json={"user_input": "Python", "doc_id": "doc_processing"},
            ),
            400,
            4001,
        )
    assert "尚未就绪" in body["message"]

