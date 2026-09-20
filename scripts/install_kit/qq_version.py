"""QQ / NapCat 版本兼容检测。

为什么需要这个模块
------------------
NapCat.Shell **不是独立程序**：它注入进官方的 QQNT 客户端（``QQ.exe``）来提供
OneBot 接口。因此 NapCat 的构建是针对**特定 QQ 版本**做的，两边对不上时典型症状是
登录后频繁被踢下线、反复掉线重连 —— 排查起来像是网络问题，实际是版本不匹配。

本会话实测过一次：目标 QQ 是 9.9.35，而所用 NapCat 面向 9.9.22，表现为持续掉线；
换成与 NapCat 匹配的 QQ 构建后恢复。

设计取舍
--------
* **只告警，不阻断**：版本对不上未必立刻不能用，且用户可能有自己的理由。
  安装器把它作为醒目提示打出来，而不是拒绝安装。
* **知识表显式集中**：已知的配套关系放在 `KNOWN_GOOD_PAIRS`，便于随上游更新；
  查不到就当"未知"，如实说明而不是猜。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: 已知可用的 NapCat : QQ 配套关系。
#:
#: 来源：本会话在 Windows 上实测确认的组合。NapCat.Shell 的 release 说明里会写明
#: 适配的 QQ 版本号，新版本出现后在这里补一行即可 —— 不要在代码里散落版本号。
KNOWN_GOOD_PAIRS: tuple[tuple[str, str], ...] = (
    # (NapCat.Shell 版本, 适配的 QQNT 版本)
    ("v4.18.28", "9.9.26-44343"),
)

#: Windows 上 QQNT 的常见安装位置（未包含的安装路径由用户显式传入）
_WINDOWS_QQ_CANDIDATES = (
    r"C:\Program Files\Tencent\QQNT\QQ.exe",
    r"C:\Program Files (x86)\Tencent\QQNT\QQ.exe",
)

#: 从文件版本号里抠出形如 9.9.26-44343 / 9.9.26.44343 / 9.9.26 的版本
_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)(?:[-.](\d+))?")


@dataclass(frozen=True)
class QQInstall:
    """一份已安装的 QQNT。"""

    path: Path
    version: str
    raw_version: str = ""

    @property
    def base(self) -> str:
        """主版本号，如 ``9.9.26``（去掉构建号）。"""
        match = _VERSION_RE.search(self.version)
        return match.group(1) if match else self.version

    @property
    def build(self) -> str:
        """构建号，如 ``44343``；没有则为空串。"""
        match = _VERSION_RE.search(self.version)
        return (match.group(2) or "") if match else ""


def parse_qq_version(raw: str) -> str:
    """把各种写法的 QQ 版本归一成 ``9.9.26-44343`` / ``9.9.26``。"""
    text = str(raw or "").strip()
    match = _VERSION_RE.search(text)
    if not match:
        return text
    base, build = match.group(1), match.group(2)
    return f"{base}-{build}" if build else base


def _read_windows_file_version(exe: Path) -> str:
    """读 PE 文件的版本资源（Windows 专用）。

    用 PowerShell 取 ``VersionInfo``，避免引入 pywin32 依赖 —— 安装器要在
    干净的机器上跑，多一个依赖就多一处失败点。
    """
    script = (
        f"(Get-Item -LiteralPath '{exe}').VersionInfo."
        "FileVersion"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (out.stdout or "").strip()


def detect_qq(explicit: str | os.PathLike[str] | None = None) -> QQInstall | None:
    """探测本机安装的 QQNT；找不到返回 None。

    ``explicit`` 可以是 ``QQ.exe`` 的路径，也可以是 QQNT 的安装目录。
    """
    candidates: list[Path] = []
    if explicit:
        given = Path(explicit)
        candidates.append(given if given.suffix.lower() == ".exe" else given / "QQ.exe")
    if sys.platform == "win32":
        candidates.extend(Path(p) for p in _WINDOWS_QQ_CANDIDATES)

    for candidate in candidates:
        if not candidate.is_file():
            continue
        raw = _read_windows_file_version(candidate) if sys.platform == "win32" else ""
        version = parse_qq_version(raw) or "unknown"
        return QQInstall(path=candidate, version=version, raw_version=raw)
    return None


@dataclass(frozen=True)
class CompatVerdict:
    """兼容性结论。"""

    level: str  # "ok" | "unknown" | "mismatch"
    message: str
    expected_qq: str = ""

    @property
    def ok(self) -> bool:
        return self.level == "ok"


def check_compat(napcat_version: str, qq: QQInstall | None) -> CompatVerdict:
    """判断 NapCat 与本机 QQ 是否配套。

    三档结论：

    * ``ok`` —— 命中已知配套表（版本号一致，或主版本一致）
    * ``mismatch`` —— 已知该 NapCat 需要别的 QQ 版本，而本机不是
    * ``unknown`` —— 该 NapCat 版本不在表里，**不猜**，如实说"未知"
    """
    napcat = str(napcat_version or "").strip()
    if qq is None:
        return CompatVerdict("unknown", "没找到本机安装的 QQNT，无法判断版本是否配套。")

    expected = next(
        (qq_ver for nap, qq_ver in KNOWN_GOOD_PAIRS if nap == napcat),
        "",
    )
    if not expected:
        return CompatVerdict(
            "unknown",
            f"没有 {napcat} 的配套记录（本机 QQ {qq.version}）。"
            "若出现频繁掉线/被踢，优先怀疑是版本不匹配。",
        )

    expected_base = expected.split("-")[0]
    if qq.version == expected or (qq.base and qq.base == expected_base):
        detail = "" if qq.version == expected else f"（主版本一致，构建号不同：{qq.version}）"
        return CompatVerdict(
            "ok",
            f"NapCat {napcat} 与本机 QQ {qq.version} 配套{detail}。",
            expected,
        )

    return CompatVerdict(
        "mismatch",
        f"版本不配套：NapCat {napcat} 面向 QQ {expected}，而本机是 {qq.version}。"
        "这种组合的典型症状是登录后频繁被踢下线、反复掉线重连 —— "
        "不是网络问题，是版本对不上。建议改装配套的 QQ 构建，或换用适配本机 QQ 的 NapCat。",
        expected,
    )


def _selftest() -> int:
    """自检：版本解析、三档结论，以及本机探测。"""
    failures = 0

    def check(label: str, got: object, want: object) -> None:
        nonlocal failures
        if got != want:
            failures += 1
            print(f"  [FAIL] {label}: got={got!r} want={want!r}")
        else:
            print(f"  [OK  ] {label}")

    print("=== 版本解析 ===")
    check("9.9.26-44343", parse_qq_version("9.9.26-44343"), "9.9.26-44343")
    check("9.9.26.44343", parse_qq_version("9.9.26.44343"), "9.9.26-44343")
    check("裸 9.9.26", parse_qq_version("9.9.26"), "9.9.26")
    check("带前缀", parse_qq_version("QQ 9.9.26-44343 x64"), "9.9.26-44343")
    check("空串", parse_qq_version(""), "")

    print("=== 兼容结论 ===")
    good = QQInstall(path=Path("X:/QQ.exe"), version="9.9.26-44343")
    check("配套 -> ok", check_compat("v4.18.28", good).level, "ok")
    same_base = QQInstall(path=Path("X:/QQ.exe"), version="9.9.26-99999")
    check("主版本一致 -> ok", check_compat("v4.18.28", same_base).level, "ok")
    bad = QQInstall(path=Path("X:/QQ.exe"), version="9.9.35-38271")
    check("不配套 -> mismatch", check_compat("v4.18.28", bad).level, "mismatch")
    check("未知 NapCat -> unknown", check_compat("v9.9.9", good).level, "unknown")
    check("没装 QQ -> unknown", check_compat("v4.18.28", None).level, "unknown")

    print("=== 本机探测 ===")
    found = detect_qq()
    if found is None:
        print("  本机未检测到 QQNT（不影响本模块正确性）")
    else:
        print(f"  找到: {found.path}")
        print(f"  版本: {found.version} (raw={found.raw_version!r})")
        verdict = check_compat("v4.18.28", found)
        print(f"  与 NapCat v4.18.28 的结论 [{verdict.level}]: {verdict.message}")

    print()
    print(f"失败 {failures} 项")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
