"""进程级重启信号：与 bot 运行时的生命周期**无关**的共享标志。

为什么需要它
------------
`POST /api/admin/restart`（面板「重启进程」）原本直接调用
`application.request_restart()`。但 application 是**每次软重启都会被替换**的
运行时对象：

* 待机时 `StandbyController._app` 已被摘成 None，注册表里仍指向**已停止**的旧对象；
* 重建失败时新对象从未注册成功，情况同上。

而 `cli.py` 的入口循环读的是 `controller.application`（待机时为 None），
于是重启信号打在旧对象上、循环永远看不到 —— 表现为「点了重启进程没有任何反应」，
用户被永久困在待机里。

这个信号由**核心**持有（软重启复用、不重建），cli 入口循环在**运行中**与
**待机**两条分支都会检查它，因此任何时刻都能逃生到进程重启。
"""

from __future__ import annotations

import threading


class ProcessRestartSignal:
    """线程安全的进程重启请求标志（只置位，由入口循环消费）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requested = False

    @property
    def requested(self) -> bool:
        """是否已请求进程重启。"""
        with self._lock:
            return self._requested

    def request(self) -> None:
        """请求进程重启（幂等）。"""
        with self._lock:
            self._requested = True

    def clear(self) -> None:
        """清除请求（测试与入口循环复用场景）。"""
        with self._lock:
            self._requested = False
