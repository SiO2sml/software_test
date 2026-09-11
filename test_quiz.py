"""quiz_service doc_id（知识库出题）分支集成测试 - 登录/归属/状态/任务校验

共 5 个用例。测试结果自包含收集：进程退出时自动打印结果表，无需修改 conftest.py。
运行：pytest -s test_quiz_service_doc_id.py
"""

import atexit
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import KnowledgeBaseError
from app.models.quiz import QuizGenerateRequest
from app.services import quiz_service


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
    print("出题功能测试结果表")
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

def _run(coro):
    """同步执行异步函数（兼容 pytest 及 Jupyter 等已有事件循环的环境）。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box = {}
    def _worker():
        try:
            box["ret"] = asyncio.run(coro)
        except BaseException as e:  # noqa: BLE001
            box["err"] = e
    import threading
    t = threading.Thread(target=_worker)
    t.start()
    t.join()
    if "err" in box:
        raise box["err"]
    return box.get("ret")


# ---------- 用例 1：登录校验 ----------

class TestHandleQuizGenerateLoginCheck:
    def test_doc_id_without_login_rejected(self, record_result):
        """出题测试：登录校验（高）——未登录用户(user_id=None)使用 doc_id 应被拒绝"""
        req = QuizGenerateRequest(
            user_input="学习 Python", question_count=5, difficulty="mixed", doc_id="doc_1"
        )

        with pytest.raises(KnowledgeBaseError, match="先登录") as exc_info:
            _run(quiz_service.handle_quiz_generate(req, user_id=None))

        print(f"\n[用例1 实际输出] 抛出 {type(exc_info.value).__name__}: {exc_info.value}")

        record_result(
            func="handle_quiz_generate",
            title="出题测试：登录校验",
            priority="高",
            precondition="无",
            input='QuizGenerateRequest(..., doc_id="doc_1")，user_id=None',
            steps="调用 handle_quiz_generate，捕获异常",
            expected='抛出异常：KnowledgeBaseError，错误信息匹配"先登录"',
            actual=f'抛出 KnowledgeBaseError("{exc_info.value}")',
        )


# ---------- 用例 2：文件不属于该用户 ----------

class TestHandleQuizGenerateDocOwnership:
    def test_doc_id_not_found_rejected(self, record_result):
        """出题测试：文件不属于该用户（高）——doc_id 不存在或不属于该用户时拒绝"""
        with patch(
            "app.services.quiz_service.knowledge_repository.get_document",
            new_callable=AsyncMock,
            return_value=None,
        ):
            req = QuizGenerateRequest(
                user_input="学习 Python",
                question_count=5,
                difficulty="mixed",
                doc_id="doc_missing",
            )
            with pytest.raises(KnowledgeBaseError, match="不存在") as exc_info:
                _run(quiz_service.handle_quiz_generate(req, user_id=1))

        print(f"\n[用例2 实际输出] 抛出 {type(exc_info.value).__name__}: {exc_info.value}")
        print('[用例2 实际输出] get_document 返回 None（文档不存在或不属于该用户）')

        record_result(
            func="handle_quiz_generate",
            title="出题测试：文件不属于该用户",
            priority="高",
            precondition="knowledge_repository.get_document 返回 None",
            input='QuizGenerateRequest(..., doc_id="doc_missing")，user_id=1',
            steps="调用 handle_quiz_generate，捕获异常",
            expected='抛出异常：KnowledgeBaseError，错误信息匹配"不存在"',
            actual=f'抛出 KnowledgeBaseError("{exc_info.value}")',
        )


# ---------- 用例 3：文档状态校验 ----------

class TestHandleQuizGenerateDocStatus:
    def test_doc_id_not_ready_rejected(self, record_result):
        """出题测试：文档状态校验（中）——上传文档后正在处理中(processing)时拒绝"""
        with patch(
            "app.services.quiz_service.knowledge_repository.get_document",
            new_callable=AsyncMock,
            return_value={"doc_id": "doc_1", "status": "processing"},
        ):
            req = QuizGenerateRequest(
                user_input="学习 Python", question_count=5, difficulty="mixed", doc_id="doc_1"
            )
            with pytest.raises(KnowledgeBaseError, match="尚未就绪") as exc_info:
                _run(quiz_service.handle_quiz_generate(req, user_id=1))

        print(f"\n[用例3 实际输出] 抛出 {type(exc_info.value).__name__}: {exc_info.value}")
        print("[用例3 实际输出] get_document 返回 status=processing（文档正在处理中）")

        record_result(
            func="handle_quiz_generate",
            title="出题测试：文档状态校验",
            priority="中",
            precondition="上传文档之后且正在处理中（status=processing）",
            input='QuizGenerateRequest(..., doc_id="doc_1")，user_id=1',
            steps="调用 handle_quiz_generate，捕获异常",
            expected='抛出异常：KnowledgeBaseError，错误信息匹配"尚未就绪"',
            actual=f'抛出 KnowledgeBaseError("{exc_info.value}")',
        )


# ---------- 用例 4：create_quiz_task 前置校验失败 ----------

class TestCreateQuizTaskValidationFailed:
    def test_invalid_doc_id_rejected_before_task_created(self, record_result):
        """出题测试：前置校验失败（高）——不创建任务记录，也不启动后台任务"""
        with patch(
            "app.services.quiz_service.knowledge_repository.get_document",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "app.services.quiz_service.task_repository.create_task", new_callable=AsyncMock
        ) as mock_create_task, patch(
            "app.services.quiz_service.asyncio.create_task"
        ) as mock_asyncio_create_task, patch(
            "app.services.quiz_service.check_content", return_value=True
        ):
            req = QuizGenerateRequest(
                user_input="学习 Python",
                question_count=5,
                difficulty="mixed",
                doc_id="doc_missing",
            )
            with pytest.raises(KnowledgeBaseError) as exc_info:
                _run(quiz_service.create_quiz_task(req, user_id=1))

        assert mock_create_task.call_count == 0
        assert mock_asyncio_create_task.call_count == 0
        print(f"\n[用例4 实际输出] 抛出 {type(exc_info.value).__name__}: {exc_info.value}")
        print(f"[用例4 实际输出] task_repository.create_task 调用 {mock_create_task.call_count} 次"
              f"（预期 0）；asyncio.create_task 调用 {mock_asyncio_create_task.call_count} 次（预期 0）")

        record_result(
            func="create_quiz_task",
            title="出题测试：前置校验失败",
            priority="高",
            precondition="get_document 返回 None；task_repository.create_task 与 asyncio.create_task 被 mock",
            input='QuizGenerateRequest(..., doc_id="doc_missing")，user_id=1',
            steps="调用 create_quiz_task，捕获异常后检查任务创建与调度情况",
            expected="抛出异常：KnowledgeBaseError；task_repository.create_task 未被调用；asyncio.create_task 未被调用",
            actual=f'抛出 KnowledgeBaseError("{exc_info.value}"); '
                   f"task_repository.create_task 调用 {mock_create_task.call_count} 次; "
                   f"asyncio.create_task 调用 {mock_asyncio_create_task.call_count} 次",
        )


# ---------- 用例 5：create_quiz_task 前置校验通过 ----------

class TestCreateQuizTaskValidationPassed:
    def test_valid_doc_id_creates_task_and_runs_with_rag(self, record_result):
        """出题测试：前置校验通过（高）——创建任务并在后台调度 RAG 出题流程"""
        with patch(
            "app.services.quiz_service.knowledge_repository.get_document",
            new_callable=AsyncMock,
            return_value={"doc_id": "doc_1", "status": "ready"},
        ), patch(
            "app.services.quiz_service.task_repository.create_task", new_callable=AsyncMock
        ) as mock_create_task, patch(
            "app.services.quiz_service.asyncio.create_task"
        ) as mock_asyncio_create_task, patch(
            "app.services.quiz_service.check_content", return_value=True
        ):
            req = QuizGenerateRequest(
                user_input="学习 Python", question_count=5, difficulty="mixed", doc_id="doc_1"
            )
            result = _run(quiz_service.create_quiz_task(req, user_id=1))

            assert result.task_id.startswith("task_")
            assert mock_create_task.call_count == 1
            assert mock_asyncio_create_task.call_count == 1
            # 关闭未被真正调度的协程，避免 "never awaited" 警告
            mock_asyncio_create_task.call_args[0][0].close()

        print(f"\n[用例5 实际输出] task_id={result.task_id}（以 task_ 开头）")
        print(f"[用例5 实际输出] task_repository.create_task 调用 {mock_create_task.call_count} 次"
              f"（预期 1）；asyncio.create_task 调用 {mock_asyncio_create_task.call_count} 次（预期 1）")

        record_result(
            func="create_quiz_task",
            title="出题测试：前置校验通过",
            priority="高",
            precondition="get_document 返回 ready 文档；任务仓库与事件循环调度均被 mock",
            input='QuizGenerateRequest(..., doc_id="doc_1")，user_id=1',
            steps="调用 create_quiz_task，检查返回值与两次 create_task 调用",
            expected="task_id 以 task_ 开头；task_repository.create_task 被调用 1 次；asyncio.create_task 被调用 1 次",
            actual=f"task_id={result.task_id}; "
                   f"task_repository.create_task 调用 {mock_create_task.call_count} 次; "
                   f"asyncio.create_task 调用 {mock_asyncio_create_task.call_count} 次",
        )