"""knowledge_repository 单元测试"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.repositories import knowledge_repository


def _make_pool(fetchone_result=None, fetchall_result=None):
    """构造一个模拟的 aiomysql pool，支持 async with pool.acquire() / conn.cursor()"""
    cursor = AsyncMock()
    cursor.fetchone = AsyncMock(return_value=fetchone_result)
    cursor.fetchall = AsyncMock(return_value=fetchall_result or [])
    cursor.execute = AsyncMock()

    cursor_cm = MagicMock()
    cursor_cm.__aenter__ = AsyncMock(return_value=cursor)
    cursor_cm.__aexit__ = AsyncMock(return_value=False)

    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cursor_cm)

    conn_cm = MagicMock()
    conn_cm.__aenter__ = AsyncMock(return_value=conn)
    conn_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn_cm)
    return pool, cursor


@pytest.mark.asyncio
async def test_create_document_executes_insert():
    pool, cursor = _make_pool()
    with patch("app.repositories.knowledge_repository.get_mysql_pool", return_value=pool):
        await knowledge_repository.create_document(
            doc_id="doc_1", user_id=1, file_name="a.pdf", file_type="pdf", file_size=1024
        )
        cursor.execute.assert_called_once()
        sql, params = cursor.execute.call_args[0]
        assert "INSERT INTO kb_documents" in sql
        assert params == ("doc_1", 1, "a.pdf", "pdf", 1024)


@pytest.mark.asyncio
async def test_update_document_status():
    pool, cursor = _make_pool()
    with patch("app.repositories.knowledge_repository.get_mysql_pool", return_value=pool):
        await knowledge_repository.update_document_status("doc_1", "ready", chunk_count=5)
        sql, params = cursor.execute.call_args[0]
        assert "UPDATE kb_documents" in sql
        assert params == ("ready", 5, None, "doc_1")


@pytest.mark.asyncio
async def test_update_document_status_failed_with_error_message():
    """解析失败路径，status=failed 时应写入 error_message，chunk_count 缺省归零"""
    pool, cursor = _make_pool()
    with patch("app.repositories.knowledge_repository.get_mysql_pool", return_value=pool):
        await knowledge_repository.update_document_status(
            "doc_1", "failed", error_message="文档解析失败"
        )
        sql, params = cursor.execute.call_args[0]
        assert "UPDATE kb_documents" in sql
        assert params == ("failed", 0, "文档解析失败", "doc_1")


@pytest.mark.asyncio
async def test_get_document_found():
    row = ("doc_1", 1, "a.pdf", "pdf", 1024, "ready", 5, None, None)
    pool, cursor = _make_pool(fetchone_result=row)
    with patch("app.repositories.knowledge_repository.get_mysql_pool", return_value=pool):
        result = await knowledge_repository.get_document("doc_1", 1)

        # 断言：查询必须同时按 doc_id + user_id 过滤，防止越权读取他人文档
        sql, params = cursor.execute.call_args[0]
        assert "WHERE doc_id = %s AND user_id = %s" in sql
        assert params == ("doc_1", 1)

        assert result["doc_id"] == "doc_1"
        assert result["status"] == "ready"
        assert result["chunk_count"] == 5


@pytest.mark.asyncio
async def test_get_document_not_found():
    pool, cursor = _make_pool(fetchone_result=None)
    with patch("app.repositories.knowledge_repository.get_mysql_pool", return_value=pool):
        result = await knowledge_repository.get_document("doc_missing", 1)
        assert result is None


@pytest.mark.asyncio
async def test_list_documents():
    rows = [
        ("doc_1", "a.pdf", "pdf", 1024, "ready", 5, None, None),
        ("doc_2", "b.docx", "docx", 2048, "processing", 0, None, None),
    ]
    pool, cursor = _make_pool(fetchall_result=rows)
    with patch("app.repositories.knowledge_repository.get_mysql_pool", return_value=pool):
        result = await knowledge_repository.list_documents(1)
        assert len(result) == 2
        assert result[0]["doc_id"] == "doc_1"
        assert result[1]["status"] == "processing"


@pytest.mark.asyncio
async def test_list_documents_empty():
    """查询结果为空时返回空列表，而不是 None"""
    pool, cursor = _make_pool(fetchall_result=[])
    with patch("app.repositories.knowledge_repository.get_mysql_pool", return_value=pool):
        result = await knowledge_repository.list_documents(1)
        assert result == []
@pytest.mark.asyncio
async def test_delete_document():
    pool, cursor = _make_pool()
    with patch("app.repositories.knowledge_repository.get_mysql_pool", return_value=pool):
        await knowledge_repository.delete_document("doc_1", 1)
        sql, params = cursor.execute.call_args[0]
        assert "DELETE FROM kb_documents" in sql
        assert params == ("doc_1", 1)
