"""软重启 / 进程重启全流程测试（入口循环与控制器/服务层）。

守住两条**回归过的真实缺陷**（现场日志证据：软重启卡在「正在停止接收器…」，
之后所有电源操作都被「运行时正在重建中，请稍候」拒绝）：

* **D1 逃生舱失效**：待机时 `application` 为 None，入口循环若不检查核心持有的
  进程重启信号，面板「重启进程」就是静默空操作 —— 用户被永久困在待机里。
* **D2 无超时 + 无自愈**：`application.stop()` 卡住会让 `resume()` 永不返回、
  `_transition` 永久为真，后续每次电源操作都被拒。

面板 HTTP 侧（`POST /api/admin/restart`）的端到端见
`app/tests/modules/builtin_plugins/test_dashboard_admin_restart.py`。
"""

from __future__ import annotations

import asyncio

import pytest

from neobot_app.bootstrap import _standby_runtime
from neobot_app.bootstrap._standby_runtime import StandbyController
from neobot_app.cli import run_entry_loop
from neobot_app.runtime.process_restart import ProcessRestartSignal
from neobot_app.runtime.standby_service import StandbyService


# ── 测试替身 ──────────────────────────────────────────────────────


class _FakeApp:
    """假运行时：可控制 stop 是否卡住。"""

    def __init__(self, *, stop_hang: bool = False, stop_seconds: float = 0.0) -> None:
        self.stopped = False
        self.started = False
        self.restart_requested = False
        self._stop_hang = stop_hang
        self._stop_seconds = stop_seconds

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        if self._stop_hang:
            await asyncio.Event().wait()  # 永不返回：模拟卡死的停止流程
        if self._stop_seconds:
            await asyncio.sleep(self._stop_seconds)
        self.stopped = True

    async def run_forever(self) -> None:
        await asyncio.sleep(0)


class _StubStandby:
    """入口循环与控制器只需要 is_standby()。"""

    def __init__(self, standby: bool = False) -> None:
        self._standby = standby

    def is_standby(self) -> bool:
        return self._standby


# ── A. 入口循环（真实 run_entry_loop）────────────────────────────


async def test_entry_loop_restarts_process_while_in_standby() -> None:
    """D1 回归：待机时收到进程重启信号必须退出循环（而不是永远 sleep）。"""
    controller = StandbyController(standby_service=_StubStandby(True), runtime_factory=_FakeApp)
    signal = ProcessRestartSignal()
    signal.request()

    result = await asyncio.wait_for(
        run_entry_loop(
            controller=controller,
            standby_service=_StubStandby(True),
            restart_signal=signal,
            state={},
            poll_interval=0.01,
        ),
        timeout=3,
    )
    assert result is True, "待机期请求重启进程时，入口循环必须返回 True 交给 execv"


async def test_entry_loop_standby_without_signal_keeps_waiting() -> None:
    """没有重启信号时待机分支应当继续等待（不能自己退出）。"""
    controller = StandbyController(standby_service=_StubStandby(True), runtime_factory=_FakeApp)
    task = asyncio.create_task(
        run_entry_loop(
            controller=controller,
            standby_service=_StubStandby(True),
            restart_signal=ProcessRestartSignal(),
            state={},
            poll_interval=0.01,
        )
    )
    await asyncio.sleep(0.1)
    assert not task.done(), "无信号时不应退出"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_entry_loop_stopping_returns_false() -> None:
    """`stopping` 置位时（正常关停）返回 False，不该触发 execv。"""
    controller = StandbyController(standby_service=_StubStandby(True), runtime_factory=_FakeApp)
    result = await asyncio.wait_for(
        run_entry_loop(
            controller=controller,
            standby_service=_StubStandby(True),
            restart_signal=ProcessRestartSignal(),
            state={"stopping": True},
            poll_interval=0.01,
        ),
        timeout=3,
    )
    assert result is False


async def test_entry_loop_resumes_after_soft_restart() -> None:
    """软重启期间（is_standby 为真）不退出，等新运行时挂上后继续。"""
    app = _FakeApp()
    controller = StandbyController(standby_service=_StubStandby(True), runtime_factory=_FakeApp)
    controller._app = app  # 直接放一个运行时；run_forever 立刻返回

    task = asyncio.create_task(
        run_entry_loop(
            controller=controller,
            standby_service=_StubStandby(True),  # 软重启中：状态仍为待机
            restart_signal=ProcessRestartSignal(),
            state={},
            poll_interval=0.01,
        )
    )
    await asyncio.sleep(0.05)
    assert not task.done(), "软重启期间循环应继续（is_standby 为真）"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ── B. StandbyController：stop 限时 / 重启信号 ───────────────────


async def test_resume_completes_even_if_stop_hangs(monkeypatch) -> None:
    """D2 回归：停止卡住时限时放行，软重启仍能完成（而不是永久挂死）。"""
    monkeypatch.setattr(_standby_runtime, "STOP_TIMEOUT_SECONDS", 0.2)
    hang = _FakeApp(stop_hang=True)
    fresh = _FakeApp()
    controller = StandbyController(
        standby_service=_StubStandby(False), runtime_factory=lambda: fresh
    )
    controller._app = hang

    ok, _message = await asyncio.wait_for(controller.resume(), timeout=5)

    assert ok is True, "stop 超时后应按已停止继续重建"
    assert controller.application is fresh, "必须换成新运行时"
    assert fresh.started is True


async def test_request_process_restart_works_without_runtime() -> None:
    """D1 回归：待机（_app 为 None）时也必须能把进程重启请求发出去。"""
    signal = ProcessRestartSignal()
    controller = StandbyController(
        standby_service=_StubStandby(True),
        runtime_factory=_FakeApp,
        restart_signal=signal,
    )

    assert controller.request_process_restart() is True
    assert signal.requested is True


async def test_request_process_restart_falls_back_to_application() -> None:
    """没有共享信号时退回运行时自身的 request_restart（兼容旧装配）。"""
    app = _FakeApp()
    calls: list[str] = []
    app.request_restart = lambda: calls.append("called")  # type: ignore[attr-defined]
    controller = StandbyController(standby_service=_StubStandby(False), runtime_factory=_FakeApp)
    controller._app = app

    assert controller.request_process_restart() is True
    assert calls == ["called"]


# ── C. StandbyService：重建看门狗（自愈）─────────────────────────


async def test_resume_watchdog_times_out_and_keeps_service_recoverable() -> None:
    """D2 回归：重建永不返回时按时失败，_transition 复位、状态回待机，且可重试。"""
    attempts = {"n": 0}

    async def _on_resume() -> tuple[bool, str]:
        attempts["n"] += 1
        if attempts["n"] == 1:
            await asyncio.Event().wait()  # 第一次：永久卡住
        return True, "已恢复"

    service = StandbyService(on_resume=_on_resume, resume_timeout=0.2)

    ok, detail = await asyncio.wait_for(service.resume(), timeout=5)

    assert ok is False
    assert "超时" in detail
    assert service.is_standby() is True
    assert service._transition is False, "看门狗必须复位 _transition，否则后续操作全被拒"

    # 自愈：同一实例再点一次软重启应当能成功
    ok2, _ = await asyncio.wait_for(service.resume(), timeout=5)
    assert ok2 is True
    assert service.is_standby() is False


async def test_resume_reports_rebuild_failure_and_stays_retryable() -> None:
    """重建抛异常时：停在待机、写明原因、仍然可以再试。"""
    attempts = {"n": 0}

    async def _on_resume() -> tuple[bool, str]:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("boom")
        return True, "已恢复"

    service = StandbyService(on_resume=_on_resume, resume_timeout=5.0)

    ok, detail = await asyncio.wait_for(service.resume(), timeout=5)
    assert ok is False
    assert "boom" in detail
    assert service.status()["reason"].startswith("软重启运行失败")
    assert service._transition is False

    assert (await asyncio.wait_for(service.resume(), timeout=5))[0] is True


async def test_resume_timeout_disabled_when_zero() -> None:
    """resume_timeout<=0 表示不设上限（保留旧行为，供测试桩使用）。"""

    async def _on_resume() -> tuple[bool, str]:
        return True, "ok"

    service = StandbyService(on_resume=_on_resume, resume_timeout=0)
    ok, _ = await service.resume()
    assert ok is True
