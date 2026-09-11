"""JWT 鉴权模块自动化测试脚本（自包含版：结果收集 + 表格输出都在本文件）

对应测试用例表：
1. create_token / decode_token —— 生成 JWT 并成功解析（高）
2. decode_token —— 错误 JWT 验证（高，篡改 token 尾部）
3. decode_token —— 过期 JWT 验证（中）
4. get_current_user —— 请求头缺少 Authorization（高）

运行方式：python -m pytest tests/test_auth.py -v -s
（-s 用于显示每个用例的 [用例N 实际输出]）
"""

import atexit

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import Request

from app.core import auth as auth_module
from app.core.auth import create_token, decode_token, get_current_user
from app.core.exceptions import AuthenticationError


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
    print("JWT 模块测试结果表")
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
    """用测试配置替换 create_token/decode_token 内部读取的配置。"""
    settings = SimpleNamespace(
        jwt_secret="test_secret_key_for_ci_0123456789abcdef",  # 32字节，消除 InsecureKeyLengthWarning
        jwt_expire_minutes=30,
    )
    monkeypatch.setattr(auth_module, "get_settings", lambda: settings)
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
    """同步执行异步依赖函数，无需安装 pytest-asyncio。"""
    return asyncio.run(coro)


# ---------- 用例 1：生成 JWT 并成功解析（高） ----------

class TestCreateAndDecodeToken:
    def test_create_and_decode_success(self, settings_mock, record_result):
        token = create_token(user_id=1, openid="openid_test_123")
        payload = decode_token(token)

        exp_dt = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        print(f"\n[用例1 实际输出] payload = {payload}")
        print(f"[用例1 实际输出] exp 对应时间 = {exp_dt:%Y-%m-%d %H:%M:%S} UTC（当前时间+30分钟）")

        assert payload["user_id"] == 1
        assert payload["openid"] == "openid_test_123"
        assert isinstance(payload["exp"], int)
        assert payload["exp"] > int(datetime.now(timezone.utc).timestamp())

        record_result(
            func="create_token / decode_token",
            title="JWT测试：生成 JWT 并成功解析",
            priority="高",
            precondition="已配置 jwt_secret 与 jwt_expire_minutes",
            input="user_id=1, openid=\"openid_test_123\"",
            steps="调用 create_token 得到 token，调用 decode_token 解析",
            expected="{\"user_id\": 1, \"openid\": \"openid_test_123\", \"exp\": <当前时间+30分钟的Unix时间戳>}",
            actual=str(payload),
        )


# ---------- 用例 2：错误 JWT 验证（高） ----------

class TestDecodeTokenInvalid:
    def test_tampered_token(self, settings_mock, record_result):
        token = create_token(user_id=1, openid="openid_test_123")
        tail = "AAAA" if token[-4:] != "AAAA" else "BBBB"
        tampered = token[:-4] + tail

        with pytest.raises(AuthenticationError, match="无效的登录凭证") as exc_info:
            decode_token(tampered)

        print(f"\n[用例2 实际输出] 抛出 {type(exc_info.value).__name__}: {exc_info.value}")

        record_result(
            func="decode_token",
            title="JWT测试：错误JWT验证",
            priority="高",
            precondition="已配置 jwt_secret",
            input="合法 token，修改后4位字符",
            steps="调用 decode_token 解析篡改后的 token",
            expected="抛出异常：无效的登录凭证",
            actual=f"抛出 AuthenticationError(\"{exc_info.value}\")",
        )

    def test_token_signed_with_wrong_secret(self, settings_mock, record_result):
        """补充用例：用错误密钥签发的 token 也应判定无效。"""
        import jwt as pyjwt

        bad_token = pyjwt.encode(
            {"user_id": 1, "openid": "openid_test_123"},
            "wrong_key_0123456789abcdef",
            algorithm="HS256",
        )
        with pytest.raises(AuthenticationError, match="无效的登录凭证") as exc_info:
            decode_token(bad_token)

        print(f"\n[用例2b 实际输出] 抛出 {type(exc_info.value).__name__}: {exc_info.value}")

        record_result(
            func="decode_token",
            title="JWT测试：错误密钥签发的token验证（补充）",
            priority="高",
            precondition="已配置 jwt_secret",
            input="用其他密钥签发的 token",
            steps="调用 decode_token 解析",
            expected="抛出异常：无效的登录凭证",
            actual=f"抛出 AuthenticationError(\"{exc_info.value}\")",
        )


# ---------- 用例 3：过期 JWT 验证（中） ----------

class TestDecodeTokenExpired:
    def test_expired_token(self, settings_mock, monkeypatch, record_result):
        expired_settings = SimpleNamespace(
            jwt_secret=settings_mock.jwt_secret,
            jwt_expire_minutes=-1,
        )
        monkeypatch.setattr(auth_module, "get_settings", lambda: expired_settings)

        token = create_token(user_id=1, openid="openid_test_123")

        with pytest.raises(AuthenticationError, match="登录已过期") as exc_info:
            decode_token(token)

        print(f"\n[用例3 实际输出] 抛出 {type(exc_info.value).__name__}: {exc_info.value}")

        record_result(
            func="decode_token",
            title="JWT测试：过期JWT验证",
            priority="中",
            precondition="已配置 jwt_secret 与 jwt_expire_minutes",
            input="过期 token（exp 设为当前时间-1分钟）",
            steps="调用 decode_token 解析过期 token",
            expected="抛出异常：登录已过期，请重新登录",
            actual=f"抛出 AuthenticationError(\"{exc_info.value}\")",
        )


# ---------- 用例 4：请求头缺少 Authorization（高） ----------

class TestGetCurrentUser:
    def test_missing_authorization_header(self, settings_mock, record_result):
        request = _make_request([])  # 无 Authorization 头

        with pytest.raises(AuthenticationError, match="未登录或登录已过期") as exc_info:
            _run(get_current_user(request))

        print(f"\n[用例4 实际输出] 抛出 {type(exc_info.value).__name__}: {exc_info.value}")

        record_result(
            func="get_current_user",
            title="JWT测试：请求头缺少 Authorization",
            priority="高",
            precondition="无",
            input="无 Authorization 头的请求",
            steps="调用 get_current_user",
            expected="抛出异常：未登录或登录已过期",
            actual=f"抛出 AuthenticationError(\"{exc_info.value}\")",
        )

    def test_valid_authorization_header(self, settings_mock, record_result):
        """补充用例：携带合法 token 时应返回 user_id。"""
        token = create_token(user_id=1, openid="openid_test_123")
        request = _make_request([(b"authorization", f"Bearer {token}".encode())])

        user_id = _run(get_current_user(request))

        print(f"\n[用例4b 实际输出] 正常返回 user_id = {user_id}")
        assert user_id == 1

        record_result(
            func="get_current_user",
            title="JWT测试：携带合法token（补充）",
            priority="高",
            precondition="已配置 jwt_secret 与 jwt_expire_minutes",
            input=f"Authorization: Bearer {token[:30]}...",
            steps="调用 get_current_user",
            expected="正常返回 user_id=1",
            actual=f"正常返回 user_id={user_id}",
        )