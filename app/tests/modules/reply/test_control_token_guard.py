"""控制词与草稿泄漏的回归测试。

两条真实泄漏路径（都有落盘证据）：

* **控制词**：模型把工具名当正文写出来 —— `content == 'cancel'` 且 `tool_calls == []`。
  它**没有**调用 `send_reply`，走的是 orchestrator 里「无工具调用但有正文」的兜底发送，
  所以只打在 `send_reply` 工具层的兜底拦不到。现在下沉到 sender 的统一清洗出口。
* **草稿**：「AI 回复检查」追问之后（该提示词要求模型用工具表态），模型若只回正文，
  那段正文是它对草稿的斟酌（实测："或者就这句？简短自然"），不是要说的话。
"""

from __future__ import annotations

import pytest

from neobot_app.reply.output_guard import clean_segments, is_control_token_only
from neobot_app.reply.sender import ReplySender


# ── 判定精度：拦得住 cancel，又不误伤正常回复 ──────────────────────


@pytest.mark.parametrize(
    "text",
    ["cancel", "CANCEL", " cancel ", "cancel。", "「cancel」", "cancel()", "cancel\n", "  “cancel”  "],
)
def test_control_token_detected(text: str) -> None:
    assert is_control_token_only(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "cancel 是什么意思",
        "为什么不 cancel 呢",
        "取消",           # 正常中文，可能是真的在回答对方
        "那我取消吧",
        "cancelled",
        "好",
        "",
        "   ",
        "cancel 和 abort 的区别",
    ],
)
def test_normal_text_not_treated_as_control_token(text: str) -> None:
    assert is_control_token_only(text) is False


# ── 发送层兜底：无工具调用的兜底路径也会被拦下 ─────────────────────


@pytest.mark.parametrize("text", ["cancel", "CANCEL", "「cancel」", "cancel。"])
def test_sender_cleans_control_token_to_empty(text: str) -> None:
    """归零后由 send_reply 的判空分支丢弃整条 —— 这是覆盖所有路径的唯一出口。"""
    assert ReplySender._clean_text_only(text, []) == ""


@pytest.mark.parametrize("text", ["cancel 是什么意思", "取消", "好哦"])
def test_sender_keeps_normal_text(text: str) -> None:
    assert ReplySender._clean_text_only(text, []) != ""


def test_sender_still_strips_annotation_prefix() -> None:
    """控制词兜底不能影响既有的标注清洗。

    注意精度：本体**故意**不剥「裸编号」——只有编号后紧跟已知发送者名字时才剥，
    否则会误伤 `3: 你好` 这类正常回复（见 output_guard 的 `_strip_bare_number`）。
    """
    assert ReplySender._clean_text_only("193: AAA大肥鱼: 我是一条鱼", ["AAA大肥鱼"]) == "我是一条鱼"


# ── 第三条路径：以 segments 形式传进来的控制词 ─────────────────────
#
# 实测漏网：模型把工具名当正文、且以 segments 传入时，两道防线同时失效 ——
# 工具层兜底要求 `not segments`，sender 的判空条件又因 segments 非空而为假。
# 因此控制词判定必须在 clean_segments 里也生效。


@pytest.mark.parametrize("token", ["cancel", "CANCEL", "「cancel」", "cancel。"])
def test_control_token_segment_is_dropped(token: str) -> None:
    assert clean_segments([token]) == []


def test_control_token_segment_does_not_take_normal_segments_with_it() -> None:
    assert clean_segments(["cancel", "真的取消了吗", "好哦"]) == ["真的取消了吗", "好哦"]


@pytest.mark.parametrize("text", ["cancel 是什么意思", "取消", "好哦"])
def test_normal_segments_survive(text: str) -> None:
    assert clean_segments([text]) == [text]


def test_segments_still_strip_annotation_prefix() -> None:
    """分句路径原有的标注清洗不能被控制词判定影响。"""
    assert clean_segments(["193: AAA大肥鱼: 我是一条鱼"], known_sender_names=["AAA大肥鱼"]) == [
        "我是一条鱼"
    ]
