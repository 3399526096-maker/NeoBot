"""好感度：UserProfileService.update_favorability 与 FavorabilitySkill 的集成测试。

回归背景：技能 `favorability` 一直调用 `profile_service.update_favorability(...)`，
而 `UserProfileService` 上**只有** `update_user_favorability(user_id, favorability)`
（另一个名字、另一种语义），于是模型每次调用好感度工具都拿到
`'UserProfileService' object has no attribute 'update_favorability'`。
本文件守住补齐后的契约：增量限幅、结果 clip、返回可读结果。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from neobot_app.skills.favorability import FavorabilitySkill
from neobot_app.user_profiles import UserProfileService


class _FakeProfilesRepo:
    """内存版 profiles 仓库。"""

    def __init__(self, initial: dict[str, int] | None = None) -> None:
        self.users: dict[str, dict[str, Any]] = {
            str(k): {"user_id": str(k), "favorability": v}
            for k, v in (initial or {}).items()
        }

    async def get_user(self, user_id: str) -> SimpleNamespace | None:
        record = self.users.get(str(user_id))
        return SimpleNamespace(**record) if record else None

    async def upsert_user(self, user_id: str, **fields: Any) -> None:
        current = self.users.setdefault(str(user_id), {"user_id": str(user_id)})
        for key, value in fields.items():
            if value is not None:
                current[key] = value


class _FakeUoW:
    def __init__(self, repo: _FakeProfilesRepo) -> None:
        self.profiles = repo

    async def __aenter__(self) -> "_FakeUoW":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def commit(self) -> None:
        return None


def _make_service(repo: _FakeProfilesRepo) -> UserProfileService:
    return UserProfileService(
        adapter=SimpleNamespace(),
        uow_factory=lambda: _FakeUoW(repo),
        config=SimpleNamespace(
            chat=SimpleNamespace(
                enable_periodic_user_info_update=False,
                user_info_update_interval_days=7,
            )
        ),
    )


# ── UserProfileService.update_favorability ────────────────────────


async def test_update_favorability_clamps_change_to_max() -> None:
    """单次变更幅度必须被限幅，否则模型能一次把好感度拉满。"""
    repo = _FakeProfilesRepo({"u1": 0})
    service = _make_service(repo)

    result = await service.update_favorability("u1", 999, max_change=5)

    assert result["before"] == 0
    assert result["after"] == 5
    assert result["change"] == 5


async def test_update_favorability_clamps_negative_change() -> None:
    repo = _FakeProfilesRepo({"u1": 100})
    service = _make_service(repo)

    result = await service.update_favorability("u1", -999, max_change=5)

    assert result["after"] == 95
    assert result["change"] == -5


async def test_update_favorability_clips_to_range() -> None:
    """结果要 clip 到 [min_value, max_value]，不能越界。"""
    repo = _FakeProfilesRepo({"u1": 998})
    service = _make_service(repo)

    result = await service.update_favorability(
        "u1", 5, max_change=5, min_value=-1000, max_value=1000
    )

    assert result["after"] == 1000
    assert result["change"] == 2, "触顶时 change 应为**实际生效**的增量"


async def test_update_favorability_at_ceiling_is_noop() -> None:
    repo = _FakeProfilesRepo({"u1": 1000})
    service = _make_service(repo)

    result = await service.update_favorability("u1", 5, max_change=5)

    assert result["after"] == 1000
    assert result["change"] == 0


async def test_update_favorability_creates_missing_user() -> None:
    """用户档案不存在时按 0 起算并创建，不应抛异常。"""
    repo = _FakeProfilesRepo()
    service = _make_service(repo)

    result = await service.update_favorability("newbie", 3, max_change=5)

    assert result["before"] == 0
    assert result["after"] == 3
    assert repo.users["newbie"]["favorability"] == 3


async def test_update_favorability_returns_readable_label() -> None:
    """返回等级文案，便于模型回读自己改到了什么程度。"""
    repo = _FakeProfilesRepo({"u1": 0})
    service = _make_service(repo)

    result = await service.update_favorability("u1", 5, max_change=5)

    assert result["label"] == "普通网友"
    assert set(result) >= {"user_id", "before", "after", "change", "label", "reason"}


async def test_update_favorability_tolerates_bad_change_value() -> None:
    """change 传了非数字时按 0 处理，不抛异常（工具层已经会挡，双保险）。"""
    repo = _FakeProfilesRepo({"u1": 10})
    service = _make_service(repo)

    result = await service.update_favorability("u1", "abc", max_change=5)  # type: ignore[arg-type]

    assert result["change"] == 0
    assert result["after"] == 10


# ── FavorabilitySkill 集成（原报错点）────────────────────────────


def _make_skill(service: Any) -> FavorabilitySkill:
    return FavorabilitySkill(profile_service=service, max_change=5,
                             min_value=-1000, max_value=1000)


async def test_skill_update_favorability_no_longer_raises_attribute_error() -> None:
    """核心回归：以前这里返回 ok=False + AttributeError 文案。"""
    repo = _FakeProfilesRepo({"u1": 0})
    skill = _make_skill(_make_service(repo))

    raw = await skill.execute("update_favorability",
                              {"user_id": "u1", "change": 4, "reason": "聊得很开心"})
    payload = __import__("json").loads(raw)

    assert payload["ok"] is True, payload
    assert "has no attribute" not in raw
    assert payload["result"]["after"] == 4
    assert payload["result"]["reason"] == "聊得很开心"


async def test_skill_rejects_missing_args() -> None:
    repo = _FakeProfilesRepo({"u1": 0})
    skill = _make_skill(_make_service(repo))

    raw = await skill.execute("update_favorability", {"user_id": "", "change": 0})
    assert '"ok": false' in raw or '"ok":false' in raw


async def test_skill_exposes_update_favorability_tool() -> None:
    repo = _FakeProfilesRepo({"u1": 0})
    skill = _make_skill(_make_service(repo))

    names = [t["function"]["name"] for t in skill.get_tools()]
    assert names == ["update_favorability"]


async def test_skill_without_profile_service_exposes_no_tools() -> None:
    """没有 profile_service 时不暴露工具（get_tools 的既有契约）。"""
    skill = _make_skill(None)
    assert skill.get_tools() == []
