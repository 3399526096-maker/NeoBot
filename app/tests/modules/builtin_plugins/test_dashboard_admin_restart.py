"""面板「重启进程」端到端：`POST /api/admin/restart` 必须落到**核心**重启信号上。

回归背景：原来该接口直接调用注册表里的 `application.request_restart()`。
application 是每次软重启都会被替换的运行时对象，而待机时它已被摘成 None、
注册表里只剩一个**已停止**的旧对象；cli 入口循环读的是 `controller.application`，
于是重启请求打在旧对象上、循环永远看不到 —— 用户点了「重启进程」毫无反应，
被困在待机里出不来。
"""

from __future__ import annotations

import asyncio

from pathlib import Path

import httpx

from neobot_app.builtin_plugins.dashboard.config import DashboardConfig
from neobot_app.builtin_plugins.dashboard.server import DashboardServer
from neobot_app.panel_auth import PanelPasswordStore
from neobot_app.runtime.process_restart import ProcessRestartSignal

from test_dashboard_api import PASSWORD, _FakeAdapter, _FakeControl, _free_port, _login


class _NullLogger:
    def debug(self, *args, **kwargs) -> None: ...
    def info(self, *args, **kwargs) -> None: ...
    def warning(self, *args, **kwargs) -> None: ...
    def error(self, *args, **kwargs) -> None: ...
    def exception(self, *args, **kwargs) -> None: ...


class _Services:
    def __init__(self, mapping: dict) -> None:
        self._mapping = mapping

    def get(self, name: str, default=None):
        return self._mapping.get(name, default)


async def _panel(tmp_path: Path, services_map: dict):
    data_dir = tmp_path / "data"
    PanelPasswordStore(data_dir / "auth.json").set_password(PASSWORD)
    config_path = tmp_path / "config.toml"
    config_path.write_text('version = "0.6.0"\n', encoding="utf-8")
    env_path = tmp_path / ".env"
    env_path.write_text("DeepSeek_APIKey=sk-test-panel\n", encoding="utf-8")
    server = DashboardServer(
        plugin_name="dashboard",
        config=DashboardConfig(host="127.0.0.1", port=_free_port()),
        data_dir=data_dir,
        logger=_NullLogger(),
        adapter=_FakeAdapter(),
        plugin_control=_FakeControl(),
        services=_Services(services_map),
        config_path=config_path,
        env_path=env_path,
        backup_dir=tmp_path / "backup",
    )
    await server.start()
    return server, f"http://127.0.0.1:{server.bound_port}"


async def _post_restart(base: str) -> httpx.Response:
    token, csrf = await _login(base)
    async with httpx.AsyncClient() as client:
        return await client.post(
            base + "/api/admin/restart",
            headers={"X-Token": token, "X-CSRF-Token": csrf},
            json={},
        )


async def _wait_until(predicate, seconds: float = 2.0) -> bool:
    for _ in range(int(seconds * 20)):
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


async def test_admin_restart_sets_core_signal(tmp_path: Path) -> None:
    """端到端：待机时点「重启进程」，核心信号必须被置位。"""
    signal = ProcessRestartSignal()
    server, base = await _panel(tmp_path, {"process_restart": signal})
    try:
        response = await _post_restart(base)
        assert response.status_code == 200, response.text
        # 路由用 call_later(0.5, ...) 稍后触发，等它落地
        assert await _wait_until(lambda: signal.requested), "重启请求必须落到核心信号上"
    finally:
        await server.stop()


async def test_admin_restart_falls_back_to_application(tmp_path: Path) -> None:
    """没有核心信号时仍走旧的 application 通道（向后兼容）。"""
    calls: list[str] = []

    class _App:
        def request_restart(self) -> None:
            calls.append("called")

    server, base = await _panel(tmp_path, {"application": _App()})
    try:
        response = await _post_restart(base)
        assert response.status_code == 200, response.text
        assert await _wait_until(lambda: bool(calls))
        assert calls == ["called"]
    finally:
        await server.stop()


async def test_admin_restart_prefers_core_signal_over_stale_application(tmp_path: Path) -> None:
    """核心信号优先于 application：待机时 application 可能是已停止的旧对象。"""
    signal = ProcessRestartSignal()
    stale_calls: list[str] = []

    class _StaleApp:
        def request_restart(self) -> None:
            stale_calls.append("called")

    server, base = await _panel(
        tmp_path, {"process_restart": signal, "application": _StaleApp()}
    )
    try:
        response = await _post_restart(base)
        assert response.status_code == 200, response.text
        assert await _wait_until(lambda: signal.requested)
        assert stale_calls == [], "不应把重启请求打在已停止的旧运行时上"
    finally:
        await server.stop()


async def test_admin_restart_reports_unavailable_without_any_entry(tmp_path: Path) -> None:
    server, base = await _panel(tmp_path, {})
    try:
        response = await _post_restart(base)
        assert response.status_code == 503
    finally:
        await server.stop()
