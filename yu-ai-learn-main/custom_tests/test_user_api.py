# -*- coding: utf-8 -*-
"""用户登录、档案与闯关历史接口验收。"""
from __future__ import annotations

import jwt
import pytest

import app.services.history_service as history_service
import app.services.user_service as user_service
from app.core.config import get_settings
from assertions import assert_error, assert_success, assert_validation_error
from conftest import CustomClient, auth_headers


def patch_profile_repositories(monkeypatch, user_row=None, quiz_count=2, answer_stats=None):
    async def get_user_by_id(user_id):
        return user_row or {
            "id": user_id,
            "openid": "openid",
            "nickname": "测试用户",
            "avatar_url": "https://example.com/a.png",
            "total_xp": 20,
        }

    async def get_quiz_count(user_id):
        return quiz_count

    async def get_answer_stats(user_id):
        return answer_stats or {"correct_count": 3, "average_accuracy": 75}

    monkeypatch.setattr(user_service.user_repository, "get_user_by_id", get_user_by_id)
    monkeypatch.setattr(user_service.quiz_repository, "get_user_quiz_count", get_quiz_count)
    monkeypatch.setattr(user_service.quiz_repository, "get_user_answer_stats", get_answer_stats)


def test_TC040_profile_requires_bearer_token():
    with CustomClient() as client:
        body = assert_error(client.get("/api/v1/user/profile"), 401, 4010)
    assert "未登录" in body["message"]


def test_TC041_profile_returns_user_and_learning_statistics(monkeypatch):
    patch_profile_repositories(monkeypatch)
    with CustomClient() as client:
        data = assert_success(client.get("/api/v1/user/profile", headers=auth_headers(3001)))
    assert data["id"] == 3001
    assert data["nickname"] == "测试用户"
    assert data["quiz_count"] == 2
    assert data["correct_count"] == 3
    assert data["average_accuracy"] == 75


def test_TC042_profile_rejects_invalid_bearer_token():
    with CustomClient() as client:
        body = assert_error(
            client.get(
                "/api/v1/user/profile",
                headers={"Authorization": "Bearer not-a-jwt"},
            ),
            401,
            4010,
        )
    assert "无效" in body["message"]


def test_TC043_update_profile_accepts_valid_nickname(monkeypatch):
    saved = {}

    async def update_profile(user_id, nickname, avatar_url):
        saved.update({"user_id": user_id, "nickname": nickname, "avatar_url": avatar_url})

    monkeypatch.setattr(user_service.user_repository, "update_user_profile", update_profile)
    with CustomClient() as client:
        assert_success(
            client.put(
                "/api/v1/user/profile",
                headers=auth_headers(3002),
                json={"nickname": "合法昵称", "avatar_url": "https://example.com/a.png"},
            )
        )
    assert saved == {
        "user_id": 3002,
        "nickname": "合法昵称",
        "avatar_url": "https://example.com/a.png",
    }


def test_TC044_update_profile_rejects_overlong_nickname(monkeypatch):
    with CustomClient() as client:
        response = client.put(
            "/api/v1/user/profile",
            headers=auth_headers(3003),
            json={"nickname": "x" * 101},
        )
    assert_validation_error(response)


def test_TC044A_update_profile_rejects_empty_nickname(monkeypatch):
    """缺陷回归：空昵称不应把用户昵称清空。"""
    with CustomClient() as client:
        response = client.put(
            "/api/v1/user/profile",
            headers=auth_headers(3003),
            json={"nickname": ""},
        )
    assert_validation_error(response)

def test_TC045_quiz_history_pagination_validates_bounds():
    with CustomClient() as client:
        response = client.get("/api/v1/user/quizzes?page=0", headers=auth_headers(3004))
        assert_validation_error(response)

        response = client.get("/api/v1/user/quizzes?page_size=51", headers=auth_headers(3004))
        assert_validation_error(response)


def test_TC046_quiz_history_returns_paged_result(monkeypatch):
    items = [
        {
            "quiz_id": "quiz_1",
            "title": "Python",
            "accuracy": 80.0,
            "question_count": 5,
            "created_at": "2026-09-20 10:00:00",
        }
    ]

    async def get_quiz_list(user_id, page, page_size):
        return items, 1

    monkeypatch.setattr(history_service.quiz_repository, "get_user_quiz_list", get_quiz_list)
    with CustomClient() as client:
        data = assert_success(
            client.get(
                "/api/v1/user/quizzes?page=1&page_size=10",
                headers=auth_headers(3005),
            )
        )
    assert data["total"] == 1
    assert data["page"] == 1
    assert data["items"][0]["quiz_id"] == "quiz_1"


def test_TC047_quiz_history_detail_missing_returns_4004(monkeypatch):
    async def missing_detail(quiz_id, user_id):
        return None

    monkeypatch.setattr(history_service.quiz_repository, "get_quiz_detail", missing_detail)
    with CustomClient() as client:
        body = assert_error(
            client.get("/api/v1/user/quizzes/no-record", headers=auth_headers(3006)),
            200,
            4004,
        )
    assert "不存在" in body["message"]


def test_TC048_wechat_login_when_not_configured_returns_auth_error():
    with CustomClient() as client:
        body = assert_error(
            client.post("/api/v1/user/login", json={"code": "wx-code"}), 401, 4010
        )
    assert "未配置" in body["message"]


def test_TC049_wechat_login_returns_jwt_and_user(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "wechat_app_id", "test-app-id", raising=False)
    monkeypatch.setattr(settings, "wechat_app_secret", "test-secret", raising=False)

    async def openid(code):
        return "openid-test"

    async def find_user(openid):
        return {
            "id": 4001,
            "openid": openid,
            "nickname": "登录用户",
            "avatar_url": "",
            "total_xp": 8,
        }

    monkeypatch.setattr(user_service, "wx_code_to_openid", openid)
    monkeypatch.setattr(user_service.user_repository, "find_user_by_openid", find_user)
    with CustomClient() as client:
        data = assert_success(client.post("/api/v1/user/login", json={"code": "valid-code"}))
    claims = jwt.decode(
        data["token"],
        settings.jwt_secret,
        algorithms=["HS256"],
        options={"verify_exp": False},
    )
    assert claims["user_id"] == 4001
    assert claims["openid"] == "openid-test"
    assert data["user"]["nickname"] == "登录用户"

