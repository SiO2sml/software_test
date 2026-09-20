# -*- coding: utf-8 -*-
"""通用断言工具。"""
from __future__ import annotations


def assert_success(response, expected_status: int = 200):
    assert response.status_code == expected_status, response.text
    body = response.json()
    assert body["code"] == 0
    assert body["message"] == "ok"
    return body["data"]


def assert_error(response, expected_status: int, expected_code: int):
    assert response.status_code == expected_status, response.text
    body = response.json()
    assert body["code"] == expected_code
    assert body["data"] is None
    assert body["message"]
    return body


def assert_validation_error(response):
    assert response.status_code == 422, response.text
    assert response.json()["detail"]
