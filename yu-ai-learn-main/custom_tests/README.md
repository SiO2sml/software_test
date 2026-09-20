# custom_tests — 独立自动化验收测试

本目录包含一套独立生成的接口/服务级自动化测试（40 条），不依赖、不引用项目原有测试脚本。测试通过 `FastAPI TestClient` 执行路由层用例，并通过 monkeypatch 隔离外部 MySQL、LLM、Tavily、DashScope、Chroma 和 COS，因此在无外部依赖环境下可重复运行。

## 目录放置要求

测试通过 `conftest.py` 定位被测后端代码，**必须把 `custom_tests` 文件夹放在项目根目录下、与 `backend` 目录同级**：

```text
项目根目录/
├── backend/          # 被测后端（FastAPI 应用）
└── custom_tests/     # 本测试目录
```

## 运行方式

### 前置条件

- Python 3.10+，且 `backend` 的依赖已安装（FastAPI、pydantic 等）。
- `pytest` 未安装时先执行：

```powershell
pip install pytest
```

### 一键运行全部用例

在**项目根目录**执行：

```powershell
python -m pytest custom_tests -q --disable-warnings
```

运行结束输出 `40 passed` 即全部通过；退出码 0 表示成功。

### 运行单条用例（可选）

```powershell
python -m pytest "custom_tests/test_user_api.py::test_TC044A_update_profile_rejects_empty_nickname" -q
```

## 覆盖范围

- 健康检查、OpenAPI、CORS
- 出题同步接口、异步任务、内容安全
- RAG 知识库限制、文档上传/状态/删除
- AI 复盘报告与计分
- 用户登录、档案、昵称校验、闯关历史
- 鉴权、参数边界和稳定错误码

## 缺陷记录

### BUG-001：用户资料更新允许空昵称清空用户昵称

- 等级：P1
- 模块：用户档案
- 缺陷现象：`PUT /api/v1/user/profile` 传入 `"nickname": ""` 时返回 HTTP 200 和 `code=0`，仓储层会把昵称更新为空字符串，导致原昵称丢失。
- 复现步骤：
  1. 使用有效 JWT 调用 `PUT /api/v1/user/profile`。
  2. 请求体传 `{"nickname": ""}`。
  3. 观察响应，并再查询用户资料。
- 预期结果：HTTP 422 参数校验失败，昵称保持不变。
- 实际结果：HTTP 200 且 `code=0`，昵称被更新为空字符串。
- 原因：`UpdateProfileRequest.nickname` 只限制 `max_length=100`，未限制最小长度。
- 修复：为 `nickname` 增加 `min_length=1`，空字符串在参数校验阶段返回 422。
- 修复验证：回归用例 `test_TC044A_update_profile_rejects_empty_nickname` 修复前失败、修复后通过；全量 40 条用例通过。
