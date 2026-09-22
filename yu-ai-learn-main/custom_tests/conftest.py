# -*- coding: utf-8 -*-
"""独立接口验收测试公共夹具。

测试只使用 FastAPI TestClient 与monkeypatch，不连接外部 MySQL/LLM/向量库。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# pytest 启动时必须先设置配置，再导入 app.main
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("MYSQL_AUTO_INIT", "false")
os.environ.setdefault("MYSQL_HOST", "invalid-test-host")
os.environ.setdefault("TAVILY_API_KEY", "")
os.environ.setdefault("ENABLE_WEB_SEARCH", "false")
os.environ.setdefault("KB_UPLOAD_DIR", str(Path(os.environ.get("TMPDIR", os.environ.get("TEMP", "."))) / "custom-kb-uploads"))
os.environ.setdefault("CHROMA_PERSIST_DIR", str(Path(os.environ.get("TMPDIR", os.environ.get("TEMP", "."))) / "custom-chroma"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.core.auth import create_token  # noqa: E402
from app.models.quiz import Question, QuestionOption, QuizOutput  # noqa: E402


def auth_headers(user_id: int = 1001) -> dict[str, str]:
    token = create_token(user_id=user_id, openid="test-openid")
    return {"Authorization": f"Bearer {token}"}


def make_quiz_output(question_count: int = 2) -> QuizOutput:
    questions = []
    for index in range(question_count):
        questions.append(
            Question(
                id=f"q{index + 1}",
                type="single",
                stem=f"第{index + 1}题题干",
                options=[
                    QuestionOption(key="A", text="选项A"),
                    QuestionOption(key="B", text="选项B"),
                ],
                answer=["A"],
                explanation="选项A正确。",
                knowledge_point=f"知识点{index + 1}",
                difficulty="easy",
            )
        )
    return QuizOutput(title="测试主题", summary="测试摘要", questions=questions)


class CustomClient:
    """同步访问 TestClient 的轻量包装，便于 yield fixture。"""

    def __init__(self):
        self.client = TestClient(app)

    def __enter__(self) -> TestClient:
        return self.client.__enter__()

    def __exit__(self, *args: Any) -> None:
        self.client.__exit__(*args)

# ---- pytest 测试结果明细 ----

_TEST_RESULTS: dict[str, tuple[str, float]] = {}


def pytest_sessionstart(session):
    """每次运行测试前清空上一轮结果。"""
    _TEST_RESULTS.clear()


def pytest_runtest_logreport(report):
    """记录每条测试用例的最终结果，跳过成功的 setup/teardown 阶段。"""
    if report.when == "setup" and report.passed:
        return
    if report.when == "teardown" and report.nodeid in _TEST_RESULTS:
        return

    if report.skipped:
        status = "SKIP"
    elif report.failed:
        status = "FAIL" if report.when == "call" else f"ERROR({report.when})"
    else:
        status = "PASS"
    _TEST_RESULTS[report.nodeid] = (status, report.duration)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """测试结束后输出每条用例的结果。"""
    if not _TEST_RESULTS:
        return

    terminalreporter.write_sep("=", "TEST CASE RESULTS")
    for index, (nodeid, (status, duration)) in enumerate(_TEST_RESULTS.items(), start=1):
        terminalreporter.write_line(f"{index:02d}. {status:<13} {duration:>6.2f}s  {nodeid}")
