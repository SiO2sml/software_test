
import pytest

from app.core.security import check_content


class TestCheckContent:
    

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
    def test_check_content(self, text, expected):
        assert check_content(text) is expected
