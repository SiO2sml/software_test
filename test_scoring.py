
import pytest

from app.models.quiz import AnswerRecord
from app.services.scoring_service import compute_score_summary


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
   

    def test_all_correct(self):
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
        print(result)

    def test_partial_correct_with_rounding(self):
        """测试 2：部分答对，验证正确率与平均用时的四舍五入"""
        records = [
            make_record("q1", True, 3000),
            make_record("q2", False, 5000),
            make_record("q3", False, 4000),
            make_record("q4", True, 2000),
            make_record("q5", False, 6000),
        ]

        result = compute_score_summary(records)
        print(result)

        
        assert result["total"] == 5
        assert result["correct"] == 2
        assert result["wrong"] == 3
        assert result["accuracy"] == 40
        assert result["avg_duration_ms"] == 4000

    

    def test_empty_records(self):
        """测试 3：空记录不得触发除零错误"""
        result = compute_score_summary([])

        assert result == {
            "total": 0,
            "correct": 0,
            "wrong": 0,
            "accuracy": 0,
            "avg_duration_ms": 0,
        }
        print(result)

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
    def test_parametrized(self, records, expected):
        """参数化回归：单题全对 / 全错 / 空记录"""
        assert compute_score_summary(records) == expected
