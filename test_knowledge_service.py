"""知识库文档业务服务自动化测试脚本（自包含版）

对应测试用例表：
1. handle_upload —— 上传大于10MB的文档（应拒绝）
2. handle_upload —— 上传非PDF/txt/word/Markdown文件（应拒绝）
3. _get_extension —— 扩展名提取
4. _process_document —— 解析文件并生成题目（chunk 向量化）
   4b.（补充）解析空文档 → 状态置为 failed

运行方式：python -m pytest tests/test_knowledge_service.py -v -s
"""

import atexit
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import KnowledgeBaseError
from app.services import knowledge_service as kb_module
from app.services.knowledge_service import _get_extension, handle_upload, _process_document


# ---------- 测试结果收集（本文件自包含，无需修改 conftest.py） ----------

RESULTS = []


@pytest.fixture
def record_result():
    """测试用例调用 record_result(...) 登记一行测试结果。"""
    def _record(func, title, priority, precondition, input, steps, expected, actual):
        RESULTS.append({
            "func": func,
            "title": title,
            "priority": priority,
            "precondition": precondition,
            "input": input,
            "steps": steps,
            "expected": expected,
            "actual": actual,
            "result": "OK",
        })
    return _record


def _print_result_table():
    """pytest 进程结束时自动输出结果表。"""
    if not RESULTS:
        return
    print()
    print("=" * 100)
    print("知识库功能测试结果表")
    print("=" * 100)
    print("测试函数 | 用例标题 | 优先级 | 前置条件 | 输入数据 | 操作步骤 | 预期输出 | 实际输出 | 结果")
    for r in RESULTS:
        print(" | ".join([
            r["func"], r["title"], r["priority"], r["precondition"],
            r["input"], r["steps"], r["expected"], r["actual"], r["result"],
        ]))
    print("=" * 100)


atexit.register(_print_result_table)


# ---------- 公共工具 ----------

@pytest.fixture
def settings_mock(monkeypatch):
    """用测试配置替换 handle_upload 内部读取的配置。"""
    settings = SimpleNamespace(
        kb_max_file_size_mb=10,
        kb_max_documents_per_user=50,
        kb_upload_dir="test_kb_upload_tmp",
    )
    monkeypatch.setattr(kb_module, "get_settings", lambda: settings)
    return settings


def _run(coro):
    """同步执行异步函数。"""
    return asyncio.run(coro)


# ---------- 用例 1：上传大于10MB的文档 ----------

class TestUploadOversizeFile:
    def test_upload_file_exceeds_10mb(self, settings_mock, record_result):
        content = b"x" * (10 * 1024 * 1024 + 1)  # 10MB + 1 字节

        with pytest.raises(KnowledgeBaseError, match="文件大小超过限制") as exc_info:
            _run(handle_upload(user_id=1, filename="big.pdf", content=content))

        print(f"\n[用例1 实际输出] 抛出 {type(exc_info.value).__name__}: {exc_info.value}")
        print(f"[用例1 实际输出] 上传大小: {len(content)/(1024*1024):.2f} MB，限制: {settings_mock.kb_max_file_size_mb} MB")

        record_result(
            func="handle_upload",
            title="知识库功能测试：上传大于10MB的文档",
            priority="高",
            precondition="已配置 kb_max_file_size_mb=10",
            input="filename=big.pdf，content=10MB+1字节",
            steps="调用 handle_upload",
            expected="抛出异常：文件大小超过限制（最大 10MB）",
            actual=f"抛出 KnowledgeBaseError(\"{exc_info.value}\")",
        )


# ---------- 用例 2：上传不支持的文件格式 ----------

class TestUploadUnsupportedFormat:
    def test_upload_exe_file(self, settings_mock, record_result):
        with pytest.raises(KnowledgeBaseError, match="不支持的文件格式") as exc_info:
            _run(handle_upload(user_id=1, filename="virus.exe", content=b"dummy content"))

        print(f"\n[用例2 实际输出] 抛出 {type(exc_info.value).__name__}: {exc_info.value}")

        record_result(
            func="handle_upload",
            title="知识库功能测试：上传非PDF/txt/word/Markdown文件",
            priority="高",
            precondition="已配置 kb_max_file_size_mb=10",
            input="filename=virus.exe，content=任意字节",
            steps="调用 handle_upload",
            expected="抛出异常：不支持的文件格式：exe，仅支持 PDF/Word/Markdown/文本文件",
            actual=f"抛出 KnowledgeBaseError(\"{exc_info.value}\")",
        )


# ---------- 用例 3：扩展名提取 ----------

class TestGetExtension:
    def test_extension_extraction(self, record_result):
        cases = {
            "report.PDF": "pdf",        # 大写扩展名 -> 转小写
            "notes.txt": "txt",
            "archive.tar.gz": "gz",     # 多后缀 -> 取最后一个
            "no_extension": "",         # 无扩展名 -> 空字符串
        }
        actual = {}
        for filename, expected_ext in cases.items():
            got = _get_extension(filename)
            actual[filename] = got
            assert got == expected_ext, f"{filename}: 期望 {expected_ext!r}, 实际 {got!r}"

        print(f"\n[用例3 实际输出] 扩展名提取结果: {actual}")

        record_result(
            func="_get_extension",
            title="知识库功能测试：扩展名提取",
            priority="中",
            precondition="无",
            input="report.PDF / notes.txt / archive.tar.gz / no_extension",
            steps="调用 _get_extension",
            expected="pdf / txt / gz / （空字符串）",
            actual=str(actual),
        )


# ---------- 用例 4：解析文件并生成题目（chunk 向量化） ----------

class TestProcessDocument:
    def _mock_services(self, monkeypatch, chunks):
        """mock 文档加载与向量写入，隔离真实文件/向量库。"""
        loader = MagicMock()
        loader.load_and_split.return_value = chunks
        vector = MagicMock()
        vector.add_document_chunks.return_value = len(chunks)
        repo = SimpleNamespace(update_document_status=AsyncMock())
        monkeypatch.setattr(kb_module, "document_loader_service", loader)
        monkeypatch.setattr(kb_module, "vector_store_service", vector)
        monkeypatch.setattr(kb_module, "knowledge_repository", repo)
        return repo

    def test_parse_document_success(self, monkeypatch, record_result):
        chunks = ["第1块内容", "第2块内容", "第3块内容"]
        repo = self._mock_services(monkeypatch, chunks)

        _run(_process_document("doc_test123", 1, "/tmp/test.pdf", "pdf"))

        repo.update_document_status.assert_awaited_once_with("doc_test123", "ready", chunk_count=3)
        print(f"\n[用例4 实际输出] 解析得到 {len(chunks)} 个 chunk，状态更新为 ready（chunk_count=3）")
        print(f"[用例4 实际输出] update_document_status 调用参数: {repo.update_document_status.call_args}")

        record_result(
            func="_process_document",
            title="知识库功能测试：解析文件并生成题目",
            priority="高",
            precondition="文档加载服务与向量库可用",
            input="doc_id=doc_test123，file_path=/tmp/test.pdf，mock 返回 3 个 chunk",
            steps="调用 _process_document，观察状态更新",
            expected="文档状态更新为 ready，chunk_count=3",
            actual="update_document_status(\"doc_test123\", \"ready\", chunk_count=3)",
        )

    def test_parse_empty_document_failed(self, monkeypatch, record_result):
        """补充用例：空文档解析失败，状态应置为 failed。"""
        repo = self._mock_services(monkeypatch, [])

        _run(_process_document("doc_empty01", 1, "/tmp/empty.pdf", "pdf"))

        repo.update_document_status.assert_awaited_once()
        args = repo.update_document_status.call_args
        assert args.args[1] == "failed"
        print(f"\n[用例4b 实际输出] 空文档解析失败，状态置为 failed")
        print(f"[用例4b 实际输出] update_document_status 调用参数: {args}")

        record_result(
            func="_process_document",
            title="知识库功能测试：解析空文档失败处理（补充）",
            priority="中",
            precondition="文档加载服务返回空 chunk 列表",
            input="doc_id=doc_empty01，mock 返回 0 个 chunk",
            steps="调用 _process_document，观察状态更新",
            expected="文档状态更新为 failed，记录错误信息",
            actual=f"update_document_status 被调用: {args}",
        )