"""出题路由"""

from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.exceptions import RateLimitError
from app.models.common import ApiResponse
from app.models.quiz import QuizGenerateRequest
from app.repositories import quiz_repository, task_repository
from app.services.quiz_service import (
    handle_quiz_generate,
    create_quiz_task,
    get_quiz_task_status,
)

router = APIRouter(prefix="/quiz", tags=["quiz"])


def _enforce_daily_limit(used_today: int) -> None:
    """每日出题限额前置校验：超限即抛限流异常。

    在任何大模型/联网搜索调用之前拦截，保证恶意请求不产生 API 费用。
    """
    limit = get_settings().quiz_gen_daily_limit
    if used_today >= limit:
        raise RateLimitError(f"今日出题次数已达上限（{limit} 次/天），请明天再来")


@router.post("/generate", response_model=ApiResponse)
async def quiz_generate(
    req: QuizGenerateRequest,
    user_id: int = Depends(get_current_user),
):
    used = await quiz_repository.count_today_sessions(user_id)
    _enforce_daily_limit(used)
    result = await handle_quiz_generate(req, user_id=user_id)
    return ApiResponse.success(data=result.model_dump())


@router.post("/generate/async", response_model=ApiResponse)
async def quiz_generate_async(
    req: QuizGenerateRequest,
    user_id: int = Depends(get_current_user),
):
    """异步创建出题任务，立即返回 task_id"""
    used = await task_repository.count_today_tasks(user_id)
    _enforce_daily_limit(used)
    result = await create_quiz_task(req, user_id=user_id)
    return ApiResponse.success(data=result.model_dump())


@router.get("/task/{task_id}", response_model=ApiResponse)
async def quiz_task_status(task_id: str):
    """轮询查询任务状态"""
    result = await get_quiz_task_status(task_id)
    return ApiResponse.success(data=result.model_dump())


@router.delete("/session/{quiz_id}", response_model=ApiResponse)
async def quiz_session_delete(
    quiz_id: str,
    user_id: int = Depends(get_current_user),
):
    """答题中途退出时删除本次出题记录，避免历史列表出现「0 题 / 0% 正确率」的误导记录。

    仅允许删除尚无答题记录的会话，已完成的闯关记录不受影响。
    """
    deleted = await quiz_repository.delete_quiz_session(quiz_id, user_id)
    return ApiResponse.success(data={"deleted": deleted})
