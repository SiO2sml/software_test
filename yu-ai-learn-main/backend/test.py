"""自动化测试总脚本（三层架构合并版，自包含：结果收集 + 分层表格输出都在本文件）

pytest 三层测试结构：层间解耦，外部依赖全部隔离
┌──────────────────────────────────────────────────────────────┐
│ API 层测试   FastAPI 请求与参数校验                            │
│              不真实启动服务，直接构造 ASGI Request 校验请求头规则 │
│ 服务层测试   Mock / Stub 隔离依赖                              │
│              MySQL 连接池、大模型、向量库、任务仓库全部用 Mock 替代│
│ 单元测试     直接调用函数并断言返回值                            │
│              parametrize 数据驱动，覆盖全对/全错/空记录等等价类与边界值│
└──────────────────────────────────────────────────────────────┘
测试基座：pytest · 参数化 + 夹具
（异步函数统一经 _run() 同步执行，无需 pytest-asyncio）

结果登记说明：
  每一条用例都通过 @recorded(...) 装饰器自动登记结果 ——
  断言通过记 OK，断言失败或抛异常记 FAIL（含异常信息），
  进程退出时按「API 层 → 服务层 → 单元测试」分组打印完整结果总表，
  不会出现"跑了但没有结果"的情况。

覆盖模块与用例：
  API 层   app.core.auth.get_current_user            —— 请求头缺少 Authorization / 携带合法 token
  服务层   app.services.knowledge_service            —— 超大文件拒绝 / 非法格式拒绝 / 解析切 chunk / 空文档失败
           app.services.quiz_service（doc_id 分支）  —— 登录校验 / 文档归属 / 状态校验 / 前置校验失败与通过
  单元测试 app.core.auth                             —— 生成并解析 JWT / 篡改 token / 错误密钥 / 过期 token
           app.services.knowledge_service._get_extension      —— 扩展名提取
           app.core.security.check_content                    —— 内容安全校验（参数化 5 组）
           app.services.scoring_service.compute_score_summary —— 成绩统计（全对/部分对/空记录/参数化回归）
           app.repositories.knowledge_repository              —— kb_documents 增删改查（mock 连接池）

运行方式：python -m pytest test.py -v -s   （本文件放在 backend/ 或 backend/tests/ 下均可）
（-s 用于显示每个用例的 [用例N 实际输出]；进程退出时自动输出分层测试结果总表）
"""

import atexit
import asyncio
import functools
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# 自动探测项目根目录（app 包所在目录）并加入模块搜索路径，
# 无论本文件放在 backend/ 还是 backend/tests/ 下、在任意目录执行 pytest 都能找到 app 模块
_HERE = Path(__file__).resolve().parent
for _candidate in (_HERE, _HERE.parent):
    if (_candidate / "app").is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

import pytest
from fastapi import Request

from app.core import auth as auth_module
from app.core.auth import create_token, decode_token, get_current_user
from app.core.exceptions import AuthenticationError, KnowledgeBaseError
from app.core.security import check_content
from app.models.quiz import AnswerRecord, QuizGenerateRequest
from app.repositories import knowledge_repository
from app.services import knowledge_service as kb_module
from app.services import quiz_service
from app.services.knowledge_service import _get_extension, _process_document, handle_upload
from app.services.scoring_service import compute_score_summary


# ======================================================================
# 测试结果收集（本文件自包含，无需修改 conftest.py）
# ======================================================================

RESULTS = []
LAYER_ORDER = ["API 层测试", "服务层测试", "单元测试"]


@pytest.fixture
def record_result():
    """登记一行测试结果（layer 标明所属层，result 为 OK / FAIL）。"""
    def _record(layer, func, title, priority, precondition, input, steps, expected, actual, result="OK"):
        RESULTS.append({
            "layer": layer,
            "func": func,
            "title": title,
            "priority": priority,
            "precondition": precondition,
            "input": input,
            "steps": steps,
            "expected": expected,
            "actual": actual,
            "result": result,
        })
    return _record


def recorded(meta):
    """用例装饰器：被装饰的测试函数 return 实际输出字符串即自动登记 OK；
    断言失败 / 抛异常时自动登记 FAIL（含异常信息）并继续抛出，保证每条用例必有结果。

    用法：
        @recorded(dict(layer=..., func=..., title=..., priority=...,
                       precondition=..., input=..., steps=..., expected=...))
        def test_xxx(self, record_result, ...):
            ...
            return "实际输出字符串"
    """
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            rec = kwargs["record_result"]
            try:
                actual = fn(*args, **kwargs)
            except BaseException as e:  # noqa: BLE001 捕获断言失败/异常，登记后继续抛出
                rec(**meta, actual=f"{type(e).__name__}: {e}", result="FAIL")
                raise
            rec(**meta, actual=str(actual), result="OK")
        return wrapper
    return deco


def _print_result_table():
    """pytest 进程结束时自动按层输出结果总表。"""
    header = "测试函数 | 用例标题 | 输入数据 | 预期输出 | 实际输出"
    print()
    print("=" * 110)
    print("三层架构自动化测试结果总表")
    print("=" * 110)
    if not RESULTS:
        print("（无任何登记结果：请检查用例是否全部被收集执行，或是否在导入阶段报错）")
    for layer in LAYER_ORDER:
        rows = [r for r in RESULTS if r["layer"] == layer]
        if not rows:
            continue
        print()
        print(f"【{layer}】共 {len(rows)} 条")
        print("-" * 110)
        print(header)
        for r in rows:
            print(" | ".join([
                r["func"], r["title"], r["input"], r["expected"], r["actual"],
            ]))
    ok = sum(1 for r in RESULTS if r["result"] == "OK")
    fail = sum(1 for r in RESULTS if r["result"] != "OK")
    print()
    print("=" * 110)
    print(f"合计 {len(RESULTS)} 条登记用例：OK {ok} 条，FAIL {fail} 条")
    print("=" * 110)


# 直接运行（python test.py）时，本模块会被 pytest 再以普通模块名导入一次并注册表格，
# 这里仅在非 __main__ 时注册，避免进程退出时多打一张空表
if __name__ != "__main__":
    atexit.register(_print_result_table)


# ======================================================================
# 公共工具（三层共用）
# ======================================================================

@pytest.fixture
def auth_settings_mock(monkeypatch):
    """用测试配置替换 create_token/decode_token 内部读取的配置。"""
    settings = SimpleNamespace(
        jwt_secret="test_secret_key_for_ci_0123456789abcdef",  # 32字节，消除 InsecureKeyLengthWarning
        jwt_expire_minutes=30,
    )
    monkeypatch.setattr(auth_module, "get_settings", lambda: settings)
    return settings


@pytest.fixture
def kb_settings_mock(monkeypatch):
    """用测试配置替换 handle_upload 内部读取的配置。"""
    settings = SimpleNamespace(
        kb_max_file_size_mb=10,
        kb_max_documents_per_user=50,
        kb_upload_dir="test_kb_upload_tmp",
    )
    monkeypatch.setattr(kb_module, "get_settings", lambda: settings)
    return settings


def _make_request(headers: list) -> Request:
    """构造一个带自定义 Header 的 FastAPI Request（ASGI scope）。"""
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
    })


def _run(coro):
    """同步执行异步函数（兼容 pytest 及 Jupyter 等已有事件循环的环境），无需 pytest-asyncio。"""
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

    t = threading.Thread(target=_worker)
    t.start()
    t.join()
    if "err" in box:
        raise box["err"]
    return box.get("ret")


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


# ======================================================================
# 第一层：API 层测试 —— FastAPI 请求与参数校验
# 不真实启动服务，直接构造 ASGI Request 校验请求头规则
# ======================================================================

class TestGetCurrentUser:
    """app.core.auth.get_current_user —— 依赖函数对 Authorization 请求头的校验"""

    @recorded(dict(
        layer="API 层测试",
        func="get_current_user",
        title="JWT测试：请求头缺少 Authorization",
        priority="高",
        precondition="无",
        input="无 Authorization 头的请求",
        steps="构造 ASGI Request（不启动真实服务），调用 get_current_user",
        expected="抛出异常：未登录或登录已过期",
    ))
    def test_missing_authorization_header(self, auth_settings_mock, record_result):
        request = _make_request([])  # 无 Authorization 头

        with pytest.raises(AuthenticationError, match="未登录或登录已过期") as exc_info:
            _run(get_current_user(request))

        print(f"\n[用例1 实际输出] 抛出 {type(exc_info.value).__name__}: {exc_info.value}")
        return f"抛出 AuthenticationError(\"{exc_info.value}\")"

    @recorded(dict(
        layer="API 层测试",
        func="get_current_user",
        title="JWT测试：携带合法token（补充）",
        priority="高",
        precondition="已配置 jwt_secret 与 jwt_expire_minutes",
        input="Authorization: Bearer <合法token>",
        steps="构造带 Bearer 头的 ASGI Request，调用 get_current_user",
        expected="正常返回 user_id=1",
    ))
    def test_valid_authorization_header(self, auth_settings_mock, record_result):
        """补充用例：携带合法 token 时应返回 user_id。"""
        token = create_token(user_id=1, openid="openid_test_123")
        request = _make_request([(b"authorization", f"Bearer {token}".encode())])

        user_id = _run(get_current_user(request))

        print(f"\n[用例1b 实际输出] 正常返回 user_id = {user_id}")
        assert user_id == 1
        return f"正常返回 user_id={user_id}"


# ======================================================================
# 第二层：服务层测试 —— Mock / Stub 隔离依赖
# MySQL 连接池、文档加载、向量库、任务仓库、内容审核全部用 Mock 替代
# ======================================================================

# ---------- 知识库文档业务服务（knowledge_service） ----------

class TestUploadOversizeFile:
    @recorded(dict(
        layer="服务层测试",
        func="handle_upload",
        title="知识库功能测试：上传大于10MB的文档",
        priority="高",
        precondition="已配置 kb_max_file_size_mb=10",
        input="filename=big.pdf，content=10MB+1字节",
        steps="调用 handle_upload",
        expected="抛出异常：文件大小超过限制（最大 10MB）",
    ))
    def test_upload_file_exceeds_10mb(self, kb_settings_mock, record_result):
        content = b"x" * (10 * 1024 * 1024 + 1)  # 10MB + 1 字节

        with pytest.raises(KnowledgeBaseError, match="文件大小超过限制") as exc_info:
            _run(handle_upload(user_id=1, filename="big.pdf", content=content))

        print(f"\n[用例2 实际输出] 抛出 {type(exc_info.value).__name__}: {exc_info.value}")
        print(f"[用例2 实际输出] 上传大小: {len(content)/(1024*1024):.2f} MB，限制: {kb_settings_mock.kb_max_file_size_mb} MB")
        return f"抛出 KnowledgeBaseError(\"{exc_info.value}\")"


class TestUploadUnsupportedFormat:
    @recorded(dict(
        layer="服务层测试",
        func="handle_upload",
        title="知识库功能测试：上传非PDF/txt/word/Markdown文件",
        priority="高",
        precondition="已配置 kb_max_file_size_mb=10",
        input="filename=virus.exe，content=任意字节",
        steps="调用 handle_upload",
        expected="抛出异常：不支持的文件格式：exe，仅支持 PDF/Word/Markdown/文本文件",
    ))
    def test_upload_exe_file(self, kb_settings_mock, record_result):
        with pytest.raises(KnowledgeBaseError, match="不支持的文件格式") as exc_info:
            _run(handle_upload(user_id=1, filename="virus.exe", content=b"dummy content"))

        print(f"\n[用例3 实际输出] 抛出 {type(exc_info.value).__name__}: {exc_info.value}")
        return f"抛出 KnowledgeBaseError(\"{exc_info.value}\")"


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

    @recorded(dict(
        layer="服务层测试",
        func="_process_document",
        title="知识库功能测试：解析文件并生成题目",
        priority="高",
        precondition="文档加载服务与向量库可用（已 mock）",
        input="doc_id=doc_test123，file_path=/tmp/test.pdf，mock 返回 3 个 chunk",
        steps="调用 _process_document，观察状态更新",
        expected="文档状态更新为 ready，chunk_count=3",
    ))
    def test_parse_document_success(self, monkeypatch, record_result):
        chunks = ["第1块内容", "第2块内容", "第3块内容"]
        repo = self._mock_services(monkeypatch, chunks)

        _run(_process_document("doc_test123", 1, "/tmp/test.pdf", "pdf"))

        repo.update_document_status.assert_awaited_once_with("doc_test123", "ready", chunk_count=3)
        print(f"\n[用例4 实际输出] 解析得到 {len(chunks)} 个 chunk，状态更新为 ready（chunk_count=3）")
        print(f"[用例4 实际输出] update_document_status 调用参数: {repo.update_document_status.call_args}")
        return "update_document_status(\"doc_test123\", \"ready\", chunk_count=3)"

    @recorded(dict(
        layer="服务层测试",
        func="_process_document",
        title="知识库功能测试：解析空文档失败处理（补充）",
        priority="中",
        precondition="文档加载服务返回空 chunk 列表",
        input="doc_id=doc_empty01，mock 返回 0 个 chunk",
        steps="调用 _process_document，观察状态更新",
        expected="文档状态更新为 failed，记录错误信息",
    ))
    def test_parse_empty_document_failed(self, monkeypatch, record_result):
        """补充用例：空文档解析失败，状态应置为 failed。"""
        repo = self._mock_services(monkeypatch, [])

        _run(_process_document("doc_empty01", 1, "/tmp/empty.pdf", "pdf"))

        repo.update_document_status.assert_awaited_once()
        args = repo.update_document_status.call_args
        assert args.args[1] == "failed"
        print(f"\n[用例4b 实际输出] 空文档解析失败，状态置为 failed")
        print(f"[用例4b 实际输出] update_document_status 调用参数: {args}")
        return f"update_document_status 被调用: {args}"


# ---------- 出题服务 doc_id（知识库出题）分支（quiz_service） ----------

class TestHandleQuizGenerateLoginCheck:
    @recorded(dict(
        layer="服务层测试",
        func="handle_quiz_generate",
        title="出题测试：登录校验",
        priority="高",
        precondition="无",
        input='QuizGenerateRequest(..., doc_id="doc_1")，user_id=None',
        steps="调用 handle_quiz_generate，捕获异常",
        expected='抛出异常：KnowledgeBaseError，错误信息匹配"先登录"',
    ))
    def test_doc_id_without_login_rejected(self, record_result):
        """出题测试：登录校验（高）——未登录用户(user_id=None)使用 doc_id 应被拒绝"""
        req = QuizGenerateRequest(
            user_input="学习 Python", question_count=5, difficulty="mixed", doc_id="doc_1"
        )

        with pytest.raises(KnowledgeBaseError, match="先登录") as exc_info:
            _run(quiz_service.handle_quiz_generate(req, user_id=None))

        print(f"\n[用例5 实际输出] 抛出 {type(exc_info.value).__name__}: {exc_info.value}")
        return f'抛出 KnowledgeBaseError("{exc_info.value}")'


class TestHandleQuizGenerateDocOwnership:
    @recorded(dict(
        layer="服务层测试",
        func="handle_quiz_generate",
        title="出题测试：文件不属于该用户",
        priority="高",
        precondition="knowledge_repository.get_document 返回 None",
        input='QuizGenerateRequest(..., doc_id="doc_missing")，user_id=1',
        steps="调用 handle_quiz_generate，捕获异常",
        expected='抛出异常：KnowledgeBaseError，错误信息匹配"不存在"',
    ))
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

        print(f"\n[用例6 实际输出] 抛出 {type(exc_info.value).__name__}: {exc_info.value}")
        print('[用例6 实际输出] get_document 返回 None（文档不存在或不属于该用户）')
        return f'抛出 KnowledgeBaseError("{exc_info.value}")'


class TestHandleQuizGenerateDocStatus:
    @recorded(dict(
        layer="服务层测试",
        func="handle_quiz_generate",
        title="出题测试：文档状态校验",
        priority="中",
        precondition="上传文档之后且正在处理中（status=processing）",
        input='QuizGenerateRequest(..., doc_id="doc_1")，user_id=1',
        steps="调用 handle_quiz_generate，捕获异常",
        expected='抛出异常：KnowledgeBaseError，错误信息匹配"尚未就绪"',
    ))
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

        print(f"\n[用例7 实际输出] 抛出 {type(exc_info.value).__name__}: {exc_info.value}")
        print("[用例7 实际输出] get_document 返回 status=processing（文档正在处理中）")
        return f'抛出 KnowledgeBaseError("{exc_info.value}")'


class TestCreateQuizTaskValidationFailed:
    @recorded(dict(
        layer="服务层测试",
        func="create_quiz_task",
        title="出题测试：前置校验失败",
        priority="高",
        precondition="get_document 返回 None；task_repository.create_task 与 asyncio.create_task 被 mock",
        input='QuizGenerateRequest(..., doc_id="doc_missing")，user_id=1',
        steps="调用 create_quiz_task，捕获异常后检查任务创建与调度情况",
        expected="抛出异常：KnowledgeBaseError；task_repository.create_task 未被调用；asyncio.create_task 未被调用",
    ))
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
        print(f"\n[用例8 实际输出] 抛出 {type(exc_info.value).__name__}: {exc_info.value}")
        print(f"[用例8 实际输出] task_repository.create_task 调用 {mock_create_task.call_count} 次"
              f"（预期 0）；asyncio.create_task 调用 {mock_asyncio_create_task.call_count} 次（预期 0）")
        return (f'抛出 KnowledgeBaseError("{exc_info.value}"); '
                f"task_repository.create_task 调用 {mock_create_task.call_count} 次; "
                f"asyncio.create_task 调用 {mock_asyncio_create_task.call_count} 次")


class TestCreateQuizTaskValidationPassed:
    @recorded(dict(
        layer="服务层测试",
        func="create_quiz_task",
        title="出题测试：前置校验通过",
        priority="高",
        precondition="get_document 返回 ready 文档；任务仓库与事件循环调度均被 mock",
        input='QuizGenerateRequest(..., doc_id="doc_1")，user_id=1',
        steps="调用 create_quiz_task，检查返回值与两次 create_task 调用",
        expected="task_id 以 task_ 开头；task_repository.create_task 被调用 1 次；asyncio.create_task 被调用 1 次",
    ))
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

        print(f"\n[用例9 实际输出] task_id={result.task_id}（以 task_ 开头）")
        print(f"[用例9 实际输出] task_repository.create_task 调用 {mock_create_task.call_count} 次"
              f"（预期 1）；asyncio.create_task 调用 {mock_asyncio_create_task.call_count} 次（预期 1）")
        return (f"task_id={result.task_id}; "
                f"task_repository.create_task 调用 {mock_create_task.call_count} 次; "
                f"asyncio.create_task 调用 {mock_asyncio_create_task.call_count} 次")


# ======================================================================
# 第三层：单元测试 —— 直接调用函数并断言返回值
# parametrize 数据驱动，覆盖全对 / 全错 / 空记录等等价类与边界值
# ======================================================================

# ---------- JWT 签发与解析（app.core.auth 纯函数） ----------

class TestCreateAndDecodeToken:
    @recorded(dict(
        layer="单元测试",
        func="create_token / decode_token",
        title="JWT测试：生成 JWT 并成功解析",
        priority="高",
        precondition="已配置 jwt_secret 与 jwt_expire_minutes",
        input="user_id=1, openid=\"openid_test_123\"",
        steps="调用 create_token 得到 token，调用 decode_token 解析",
        expected="{\"user_id\": 1, \"openid\": \"openid_test_123\", \"exp\": <当前时间+30分钟的Unix时间戳>}",
    ))
    def test_create_and_decode_success(self, auth_settings_mock, record_result):
        token = create_token(user_id=1, openid="openid_test_123")
        payload = decode_token(token)

        exp_dt = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        print(f"\n[用例10 实际输出] payload = {payload}")
        print(f"[用例10 实际输出] exp 对应时间 = {exp_dt:%Y-%m-%d %H:%M:%S} UTC（当前时间+30分钟）")

        assert payload["user_id"] == 1
        assert payload["openid"] == "openid_test_123"
        assert isinstance(payload["exp"], int)
        assert payload["exp"] > int(datetime.now(timezone.utc).timestamp())
        return str(payload)


class TestDecodeTokenInvalid:
    @recorded(dict(
        layer="单元测试",
        func="decode_token",
        title="JWT测试：错误JWT验证",
        priority="高",
        precondition="已配置 jwt_secret",
        input="合法 token，修改后4位字符",
        steps="调用 decode_token 解析篡改后的 token",
        expected="抛出异常：无效的登录凭证",
    ))
    def test_tampered_token(self, auth_settings_mock, record_result):
        token = create_token(user_id=1, openid="openid_test_123")
        tail = "AAAA" if token[-4:] != "AAAA" else "BBBB"
        tampered = token[:-4] + tail

        with pytest.raises(AuthenticationError, match="无效的登录凭证") as exc_info:
            decode_token(tampered)

        print(f"\n[用例11 实际输出] 抛出 {type(exc_info.value).__name__}: {exc_info.value}")
        return f"抛出 AuthenticationError(\"{exc_info.value}\")"

    @recorded(dict(
        layer="单元测试",
        func="decode_token",
        title="JWT测试：错误密钥签发的token验证（补充）",
        priority="高",
        precondition="已配置 jwt_secret",
        input="用其他密钥签发的 token",
        steps="调用 decode_token 解析",
        expected="抛出异常：无效的登录凭证",
    ))
    def test_token_signed_with_wrong_secret(self, auth_settings_mock, record_result):
        """补充用例：用错误密钥签发的 token 也应判定无效。"""
        import jwt as pyjwt

        bad_token = pyjwt.encode(
            {"user_id": 1, "openid": "openid_test_123"},
            "wrong_key_0123456789abcdef",
            algorithm="HS256",
        )
        with pytest.raises(AuthenticationError, match="无效的登录凭证") as exc_info:
            decode_token(bad_token)

        print(f"\n[用例11b 实际输出] 抛出 {type(exc_info.value).__name__}: {exc_info.value}")
        return f"抛出 AuthenticationError(\"{exc_info.value}\")"


class TestDecodeTokenExpired:
    @recorded(dict(
        layer="单元测试",
        func="decode_token",
        title="JWT测试：过期JWT验证",
        priority="中",
        precondition="已配置 jwt_secret 与 jwt_expire_minutes",
        input="过期 token（exp 设为当前时间-1分钟）",
        steps="调用 decode_token 解析过期 token",
        expected="抛出异常：登录已过期，请重新登录",
    ))
    def test_expired_token(self, auth_settings_mock, monkeypatch, record_result):
        expired_settings = SimpleNamespace(
            jwt_secret=auth_settings_mock.jwt_secret,
            jwt_expire_minutes=-1,
        )
        monkeypatch.setattr(auth_module, "get_settings", lambda: expired_settings)

        token = create_token(user_id=1, openid="openid_test_123")

        with pytest.raises(AuthenticationError, match="登录已过期") as exc_info:
            decode_token(token)

        print(f"\n[用例12 实际输出] 抛出 {type(exc_info.value).__name__}: {exc_info.value}")
        return f"抛出 AuthenticationError(\"{exc_info.value}\")"


# ---------- 扩展名提取（knowledge_service 纯函数） ----------

class TestGetExtension:
    @recorded(dict(
        layer="单元测试",
        func="_get_extension",
        title="知识库功能测试：扩展名提取",
        priority="中",
        precondition="无",
        input="report.PDF / notes.txt / archive.tar.gz / no_extension",
        steps="调用 _get_extension",
        expected="pdf / txt / gz / （空字符串）",
    ))
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

        print(f"\n[用例13 实际输出] 扩展名提取结果: {actual}")
        return str(actual)


# ---------- 内容安全校验（app.core.security 纯函数，参数化数据驱动） ----------

class TestCheckContent:
    """app.core.security.check_content —— 等价类 + 边界值，parametrize 数据驱动"""

    @pytest.mark.parametrize(
        "text, expected",
        [
            # 场景 1：正常学习内容，应当通过
            ("我想学习 Python 基础语法", True),
            # 场景 2：敏感词嵌在句子中间（子串匹配应命中）
            ("请帮我出一套关于赌博危害的题目", False),
            # 场景 3：空字符串边界，视为安全
            ("", True),
            # 场景 4：多个敏感词同时出现，任一命中即拒绝
            ("恐怖分子使用炸弹和武器", False),
            # 场景 5：近似词但不含完整敏感词，不应误伤
            ("这段代码性能爆破式提升，效率翻倍", True),
        ],
        ids=[
            "normal-content",
            "blocked-keyword-embedded",
            "empty-string",
            "multiple-blocked-keywords",
            "similar-safe-word",
        ],
    )
    @recorded(dict(
        layer="单元测试",
        func="check_content",
        title="内容安全校验：参数化 5 组（正常/嵌敏感词/空串/多敏感词/近似词）",
        priority="高",
        precondition="无",
        input="见各参数组 text",
        steps="调用 check_content，断言返回值",
        expected="各参数组 expected 值（True=放行 / False=拦截）",
    ))
    def test_check_content(self, record_result, text, expected):
        got = check_content(text)
        print(f"\n[用例14 实际输出] check_content({text!r}) = {got}（预期 {expected}）")
        assert got is expected
        return f"check_content({text!r}) = {got}"


# ---------- 成绩统计（scoring_service 纯函数） ----------

def make_record(
    question_id: str,
    is_correct: bool,
    duration_ms: int,
    selected: list[str] | None = None,
) -> AnswerRecord:
    return AnswerRecord(
        question_id=question_id,
        selected_answers=selected or (["A"] if is_correct else ["B"]),
        is_correct=is_correct,
        duration_ms=duration_ms,
    )


class TestComputeScoreSummary:
    """app.services.scoring_service.compute_score_summary —— 全对 / 部分对 / 空记录 + 参数化回归"""

    @recorded(dict(
        layer="单元测试",
        func="compute_score_summary",
        title="成绩统计：全部答对",
        priority="高",
        precondition="无",
        input="2 条答题记录，全部答对，用时 3000ms / 4000ms",
        steps="调用 compute_score_summary",
        expected='{"total": 2, "correct": 2, "wrong": 0, "accuracy": 100, "avg_duration_ms": 3500}',
    ))
    def test_all_correct(self, record_result):
        """测试 1：全部答对，正确率应为 100%"""
        records = [
            make_record("q1", True, 3000),
            make_record("q2", True, 4000),
        ]

        result = compute_score_summary(records)

        assert result == {
            "total": 2,
            "correct": 2,
            "wrong": 0,
            "accuracy": 100,
            "avg_duration_ms": 3500,
        }
        print(f"\n[用例15a 实际输出] {result}")
        return str(result)

    @recorded(dict(
        layer="单元测试",
        func="compute_score_summary",
        title="成绩统计：部分答对（验证四舍五入）",
        priority="高",
        precondition="无",
        input="5 条答题记录，2 对 3 错，用时 3000/5000/4000/2000/6000ms",
        steps="调用 compute_score_summary",
        expected="total=5, correct=2, wrong=3, accuracy=40, avg_duration_ms=4000",
    ))
    def test_partial_correct_with_rounding(self, record_result):
        """测试 2：部分答对，验证正确率与平均用时的四舍五入"""
        records = [
            make_record("q1", True, 3000),
            make_record("q2", False, 5000),
            make_record("q3", False, 4000),
            make_record("q4", True, 2000),
            make_record("q5", False, 6000),
        ]

        result = compute_score_summary(records)
        print(f"\n[用例15b 实际输出] {result}")

        assert result["total"] == 5
        assert result["correct"] == 2
        assert result["wrong"] == 3
        assert result["accuracy"] == 40
        assert result["avg_duration_ms"] == 4000
        return str(result)

    @recorded(dict(
        layer="单元测试",
        func="compute_score_summary",
        title="成绩统计：空记录边界",
        priority="高",
        precondition="无",
        input="空列表 []",
        steps="调用 compute_score_summary",
        expected='{"total": 0, "correct": 0, "wrong": 0, "accuracy": 0, "avg_duration_ms": 0}，不触发除零错误',
    ))
    def test_empty_records(self, record_result):
        """测试 3：空记录不得触发除零错误"""
        result = compute_score_summary([])

        assert result == {
            "total": 0,
            "correct": 0,
            "wrong": 0,
            "accuracy": 0,
            "avg_duration_ms": 0,
        }
        print(f"\n[用例15c 实际输出] {result}")
        return str(result)

    @pytest.mark.parametrize(
        "records, expected",
        [
            # 全对
            (
                [make_record("q1", True, 1000)],
                {"total": 1, "correct": 1, "wrong": 0, "accuracy": 100, "avg_duration_ms": 1000},
            ),
            # 全错
            (
                [make_record("q1", False, 2000)],
                {"total": 1, "correct": 0, "wrong": 1, "accuracy": 0, "avg_duration_ms": 2000},
            ),
            # 空列表
            (
                [],
                {"total": 0, "correct": 0, "wrong": 0, "accuracy": 0, "avg_duration_ms": 0},
            ),
        ],
        ids=["single-all-correct", "single-all-wrong", "empty"],
    )
    @recorded(dict(
        layer="单元测试",
        func="compute_score_summary",
        title="成绩统计：参数化回归（单题全对/全错/空记录）",
        priority="中",
        precondition="无",
        input="见各参数组 records",
        steps="调用 compute_score_summary，断言结果字典",
        expected="各参数组 expected 字典",
    ))
    def test_parametrized(self, record_result, records, expected):
        """参数化回归：单题全对 / 全错 / 空记录"""
        result = compute_score_summary(records)
        print(f"\n[用例15p 实际输出] records={len(records)} 条 -> {result}")
        assert result == expected
        return str(result)


# ---------- 知识库仓储层（knowledge_repository，mock aiomysql 连接池，不连真实数据库） ----------

class TestKnowledgeRepository:
    """app.repositories.knowledge_repository —— kb_documents 增删改查 SQL 与参数校验"""

    @recorded(dict(
        layer="单元测试",
        func="knowledge_repository.create_document",
        title="仓储层：新增文档记录",
        priority="高",
        precondition="mock aiomysql 连接池",
        input='doc_id="doc_1", user_id=1, file_name="a.pdf", file_type="pdf", file_size=1024',
        steps="调用 create_document，校验执行的 SQL 与参数",
        expected='执行一次 INSERT INTO kb_documents，参数 ("doc_1", 1, "a.pdf", "pdf", 1024)',
    ))
    def test_create_document_executes_insert(self, record_result):
        pool, cursor = _make_pool()
        with patch("app.repositories.knowledge_repository.get_mysql_pool", return_value=pool):
            _run(knowledge_repository.create_document(
                doc_id="doc_1", user_id=1, file_name="a.pdf", file_type="pdf", file_size=1024
            ))
            cursor.execute.assert_called_once()
            sql, params = cursor.execute.call_args[0]
            assert "INSERT INTO kb_documents" in sql
            assert params == ("doc_1", 1, "a.pdf", "pdf", 1024)
        print(f"\n[用例16a 实际输出] SQL = {sql.strip()} | params = {params}")
        return f"INSERT 已执行，params={params}"

    @recorded(dict(
        layer="单元测试",
        func="knowledge_repository.update_document_status",
        title="仓储层：更新文档状态为 ready",
        priority="高",
        precondition="mock aiomysql 连接池",
        input='"doc_1", "ready", chunk_count=5',
        steps="调用 update_document_status，校验 SQL 与参数",
        expected='执行 UPDATE kb_documents，参数 ("ready", 5, None, "doc_1")',
    ))
    def test_update_document_status(self, record_result):
        pool, cursor = _make_pool()
        with patch("app.repositories.knowledge_repository.get_mysql_pool", return_value=pool):
            _run(knowledge_repository.update_document_status("doc_1", "ready", chunk_count=5))
            sql, params = cursor.execute.call_args[0]
            assert "UPDATE kb_documents" in sql
            assert params == ("ready", 5, None, "doc_1")
        print(f"\n[用例16b 实际输出] SQL = {sql.strip()} | params = {params}")
        return f"UPDATE 已执行，params={params}"

    @recorded(dict(
        layer="单元测试",
        func="knowledge_repository.update_document_status",
        title="仓储层：解析失败写入 error_message",
        priority="中",
        precondition="mock aiomysql 连接池",
        input='"doc_1", "failed", error_message="文档解析失败"',
        steps="调用 update_document_status，校验 SQL 与参数",
        expected='执行 UPDATE kb_documents，参数 ("failed", 0, "文档解析失败", "doc_1")（chunk_count 缺省归零）',
    ))
    def test_update_document_status_failed_with_error_message(self, record_result):
        """解析失败路径，status=failed 时应写入 error_message，chunk_count 缺省归零"""
        pool, cursor = _make_pool()
        with patch("app.repositories.knowledge_repository.get_mysql_pool", return_value=pool):
            _run(knowledge_repository.update_document_status(
                "doc_1", "failed", error_message="文档解析失败"
            ))
            sql, params = cursor.execute.call_args[0]
            assert "UPDATE kb_documents" in sql
            assert params == ("failed", 0, "文档解析失败", "doc_1")
        print(f"\n[用例16c 实际输出] SQL = {sql.strip()} | params = {params}")
        return f"UPDATE 已执行，params={params}"

    @recorded(dict(
        layer="单元测试",
        func="knowledge_repository.get_document",
        title="仓储层：按 doc_id+user_id 查询文档（防越权）",
        priority="高",
        precondition="mock 连接池返回一条 ready 文档行",
        input='"doc_1", user_id=1',
        steps="调用 get_document，校验 SQL 过滤条件与返回字段",
        expected='SQL 含 WHERE doc_id = %s AND user_id = %s；返回 doc_id/status/chunk_count 正确',
    ))
    def test_get_document_found(self, record_result):
        row = ("doc_1", 1, "a.pdf", "pdf", 1024, "ready", 5, None, None)
        pool, cursor = _make_pool(fetchone_result=row)
        with patch("app.repositories.knowledge_repository.get_mysql_pool", return_value=pool):
            result = _run(knowledge_repository.get_document("doc_1", 1))

            # 断言：查询必须同时按 doc_id + user_id 过滤，防止越权读取他人文档
            sql, params = cursor.execute.call_args[0]
            assert "WHERE doc_id = %s AND user_id = %s" in sql
            assert params == ("doc_1", 1)

            assert result["doc_id"] == "doc_1"
            assert result["status"] == "ready"
            assert result["chunk_count"] == 5
        print(f"\n[用例16d 实际输出] result = {result}")
        return f"返回文档: doc_id={result['doc_id']}, status={result['status']}, chunk_count={result['chunk_count']}"

    @recorded(dict(
        layer="单元测试",
        func="knowledge_repository.get_document",
        title="仓储层：文档不存在返回 None",
        priority="中",
        precondition="mock 连接池返回空",
        input='"doc_missing", user_id=1',
        steps="调用 get_document",
        expected="返回 None",
    ))
    def test_get_document_not_found(self, record_result):
        pool, cursor = _make_pool(fetchone_result=None)
        with patch("app.repositories.knowledge_repository.get_mysql_pool", return_value=pool):
            result = _run(knowledge_repository.get_document("doc_missing", 1))
            assert result is None
        print(f"\n[用例16e 实际输出] result = {result}")
        return "返回 None"

    @recorded(dict(
        layer="单元测试",
        func="knowledge_repository.list_documents",
        title="仓储层：列出用户文档（2 条）",
        priority="高",
        precondition="mock 连接池返回 2 行（ready / processing）",
        input="user_id=1",
        steps="调用 list_documents",
        expected="返回长度为 2 的列表，字段映射正确",
    ))
    def test_list_documents(self, record_result):
        rows = [
            ("doc_1", "a.pdf", "pdf", 1024, "ready", 5, None, None),
            ("doc_2", "b.docx", "docx", 2048, "processing", 0, None, None),
        ]
        pool, cursor = _make_pool(fetchall_result=rows)
        with patch("app.repositories.knowledge_repository.get_mysql_pool", return_value=pool):
            result = _run(knowledge_repository.list_documents(1))
            assert len(result) == 2
            assert result[0]["doc_id"] == "doc_1"
            assert result[1]["status"] == "processing"
        print(f"\n[用例16f 实际输出] result = {result}")
        return f"返回 {len(result)} 条: doc_1(ready), doc_2(processing)"

    @recorded(dict(
        layer="单元测试",
        func="knowledge_repository.list_documents",
        title="仓储层：空结果返回空列表",
        priority="中",
        precondition="mock 连接池返回空",
        input="user_id=1",
        steps="调用 list_documents",
        expected="返回 []（而不是 None）",
    ))
    def test_list_documents_empty(self, record_result):
        """查询结果为空时返回空列表，而不是 None"""
        pool, cursor = _make_pool(fetchall_result=[])
        with patch("app.repositories.knowledge_repository.get_mysql_pool", return_value=pool):
            result = _run(knowledge_repository.list_documents(1))
            assert result == []
        print(f"\n[用例16g 实际输出] result = {result}")
        return "返回 []"

    @recorded(dict(
        layer="单元测试",
        func="knowledge_repository.delete_document",
        title="仓储层：删除文档记录",
        priority="高",
        precondition="mock aiomysql 连接池",
        input='"doc_1", user_id=1',
        steps="调用 delete_document，校验 SQL 与参数",
        expected='执行 DELETE FROM kb_documents，参数 ("doc_1", 1)',
    ))
    def test_delete_document(self, record_result):
        pool, cursor = _make_pool()
        with patch("app.repositories.knowledge_repository.get_mysql_pool", return_value=pool):
            _run(knowledge_repository.delete_document("doc_1", 1))
            sql, params = cursor.execute.call_args[0]
            assert "DELETE FROM kb_documents" in sql
            assert params == ("doc_1", 1)
        print(f"\n[用例16h 实际输出] SQL = {sql.strip()} | params = {params}")
        return f"DELETE 已执行，params={params}"


# ======================================================================
# 直接执行入口：python test.py 等价于 python -m pytest test.py -v -s
# ======================================================================

if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-s"]))