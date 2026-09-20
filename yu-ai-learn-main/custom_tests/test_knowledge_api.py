# -*- coding: utf-8 -*-
"""知识库文档上传、查询、删除与RAG限制验收。"""
from __future__ import annotations

import pytest

import app.services.knowledge_service as knowledge_service
from assertions import assert_error, assert_success, assert_validation_error
from conftest import CustomClient, auth_headers


@pytest.fixture(autouse=True)
def prevent_background_processing(monkeypatch):
    async def no_process(*args, **kwargs):
        return None

    monkeypatch.setattr(knowledge_service, "_process_document", no_process)


def test_TC050_knowledge_document_upload_requires_login():
    with CustomClient() as client:
        body = assert_error(
            client.post(
                "/api/v1/knowledge/documents",
                files={"file": ("notes.txt", b"hello", "text/plain")},
            ),
            401,
            4010,
        )
    assert "未登录" in body["message"]


def test_TC051_knowledge_document_upload_rejects_unsupported_extension():
    with CustomClient() as client:
        body = assert_error(
            client.post(
                "/api/v1/knowledge/documents",
                headers=auth_headers(5001),
                files={"file": ("virus.exe", b"binary", "application/octet-stream")},
            ),
            400,
            4001,
        )
    assert "不支持的文件格式" in body["message"]


def test_TC052_knowledge_document_upload_rejects_oversized_file(monkeypatch):
    settings = knowledge_service.get_settings()
    monkeypatch.setattr(settings, "kb_max_file_size_mb", 1, raising=False)
    content = b"a" * (1024 * 1024 + 1)
    with CustomClient() as client:
        body = assert_error(
            client.post(
                "/api/v1/knowledge/documents",
                headers=auth_headers(5002),
                files={"file": ("large.txt", content, "text/plain")},
            ),
            400,
            4001,
        )
    assert "文件大小超过限制" in body["message"]


def test_TC053_knowledge_document_upload_returns_processing_status(monkeypatch):
    saved = {}

    async def create_document(**kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(knowledge_service.knowledge_repository, "create_document", create_document)
    with CustomClient() as client:
        data = assert_success(
            client.post(
                "/api/v1/knowledge/documents",
                headers=auth_headers(5003),
                files={"file": ("notes.txt", b"FastAPI notes", "text/plain")},
            )
        )
    assert data["doc_id"].startswith("doc_")
    assert data["file_name"] == "notes.txt"
    assert data["status"] == "processing"
    assert saved["user_id"] == 5003


def test_TC054_knowledge_document_status_not_found_returns_4001(monkeypatch):
    async def missing_document(doc_id, user_id):
        return None

    monkeypatch.setattr(knowledge_service.knowledge_repository, "get_document", missing_document)
    with CustomClient() as client:
        body = assert_error(
            client.get("/api/v1/knowledge/documents/doc_none", headers=auth_headers(5004)),
            400,
            4001,
        )
    assert "文档不存在" in body["message"]


def test_TC055_knowledge_document_list_is_scoped_to_owner(monkeypatch):
    rows = [
        {
            "doc_id": "doc_1",
            "file_name": "Python.md",
            "file_type": "md",
            "file_size": 12,
            "status": "ready",
            "chunk_count": 2,
            "error_message": None,
            "created_at": "2026-09-20 10:00:00",
        }
    ]

    async def list_documents(user_id):
        assert user_id == 5005
        return rows

    monkeypatch.setattr(knowledge_service.knowledge_repository, "list_documents", list_documents)
    with CustomClient() as client:
        data = assert_success(
            client.get("/api/v1/knowledge/documents", headers=auth_headers(5005))
        )
    assert data["items"][0]["doc_id"] == "doc_1"
    assert data["items"][0]["status"] == "ready"


def test_TC056_knowledge_document_delete_missing_returns_4001(monkeypatch):
    async def missing_document(doc_id, user_id):
        return None

    async def forbidden_delete(doc_id, user_id):
        raise AssertionError("不存在文档不应执行删除")

    monkeypatch.setattr(knowledge_service.knowledge_repository, "get_document", missing_document)
    monkeypatch.setattr(knowledge_service.knowledge_repository, "delete_document", forbidden_delete)
    with CustomClient() as client:
        body = assert_error(
            client.delete("/api/v1/knowledge/documents/doc_none", headers=auth_headers(5006)),
            400,
            4001,
        )
    assert "文档不存在" in body["message"]


def test_TC057_knowledge_document_delete_cleans_vectors_file_and_record(monkeypatch, tmp_path):
    settings = knowledge_service.get_settings()
    monkeypatch.setattr(settings, "kb_upload_dir", str(tmp_path), raising=False)
    file_path = tmp_path / "doc_ready.txt"
    file_path.write_text("content", encoding="utf-8")
    calls = []

    async def existing_document(doc_id, user_id):
        return {"doc_id": doc_id, "file_type": "txt"}

    def delete_vectors(user_id, doc_id):
        calls.append(("vector", user_id, doc_id))

    async def delete_document(doc_id, user_id):
        calls.append(("db", doc_id, user_id))

    monkeypatch.setattr(knowledge_service.knowledge_repository, "get_document", existing_document)
    monkeypatch.setattr(knowledge_service.vector_store_service, "delete_document_vectors", delete_vectors)
    monkeypatch.setattr(knowledge_service.knowledge_repository, "delete_document", delete_document)
    with CustomClient() as client:
        assert_success(
            client.delete("/api/v1/knowledge/documents/doc_ready", headers=auth_headers(5007))
        )
    assert ("vector", 5007, "doc_ready") in calls
    assert ("db", "doc_ready", 5007) in calls
    assert not file_path.exists()


def test_TC058_quiz_with_ready_doc_uses_rag_context(monkeypatch):
    import app.services.quiz_service as quiz_service

    async def ready_doc(doc_id, user_id):
        return {"status": "ready"}

    async def rag_context(user_input, user_id, doc_id):
        assert user_id == 5008
        assert doc_id == "doc_ready"
        return "RAG上下文"

    async def generate_quiz(**kwargs):
        assert kwargs["search_context"] == "RAG上下文"
        from conftest import make_quiz_output
        return make_quiz_output(1)

    monkeypatch.setattr(quiz_service.knowledge_repository, "get_document", ready_doc)
    monkeypatch.setattr(quiz_service.rag_service, "fetch_rag_context", rag_context)
    monkeypatch.setattr(quiz_service, "generate_quiz", generate_quiz)
    with CustomClient() as client:
        data = assert_success(
            client.post(
                "/api/v1/quiz/generate",
                headers=auth_headers(5008),
                json={"user_input": "Python", "doc_id": "doc_ready"},
            )
        )
    assert len(data["questions"]) == 1

