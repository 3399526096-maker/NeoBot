"""NeoBot 懒人安装器。

在目标机器上跑一条命令，把环境搭起来：

    python install.py                     # 装到 ./neobot
    python install.py --target D:\\neobot  # 指定安装目录
    python install.py --dry-run           # 只打印将要做什么

它会依次完成：
  1. 检查 Python 版本（NeoBot 要求 >= 3.13）
  2. 建虚拟环境
  3. 安装 neobot-app（优先用同目录下的离线 wheelhouse，没有再走 PyPI）
  4. 初始化数据目录、.env 与启动脚本
  5. NapCat：本目录若有 napcat/ 就解压过去，并**检查它和本机 QQ 的版本是否配套**
     （这一步不是可选项 —— 版本对不上会表现为持续掉线，很难排查）

设计原则
--------
* **不静默失败**：每一步的输出都打出来，失败立刻停并说明原因。
* **可重入**：重复运行不会破坏已装好的环境（已存在的 venv/数据目录会被保留）。
* **不代替用户做危险决定**：不自动卸载/覆盖本机 QQ，也不改动它的安装。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import venv
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qq_version import check_compat, detect_qq  # noqa: E402

#: NeoBot 需要的最低 Python 版本（见 app/pyproject.toml 的 requires-python）
MIN_PYTHON = (3, 13)

#: 分发包里的约定目录名
WHEELHOUSE_DIR = "wheels"
NAPCAT_DIR = "napcat"

DEFAULT_NAPCAT_VERSION = "v4.18.28"


def log(message: str = "") -> None:
    print(message, flush=True)


def step(title: str) -> None:
    log()
    log("─" * 66)
    log(title)
    log("─" * 66)


def run(cmd: list[str], *, dry_run: bool, cwd: Path | None = None) -> int:
    log(f"  $ {' '.join(cmd)}")
    if dry_run:
        return 0
    result = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    return result.returncode


def check_python() -> bool:
    step("1/5  检查 Python 版本")
    current = sys.version_info[:3]
    log(f"  当前: {current[0]}.{current[1]}.{current[2]}  ({sys.executable})")
    if current[:2] < MIN_PYTHON:
        log(f"  × 需要 Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 或更高。")
        log("    请先安装新版 Python（安装时勾选 'Add to PATH'）后重试。")
        return False
    log("  √ 版本满足要求")
    return True


def make_venv(target: Path, *, dry_run: bool) -> Path | None:
    step("2/5  建虚拟环境")
    env_dir = target / "neobot-env"
    if env_dir.is_dir():
        log(f"  已存在，保留: {env_dir}")
        return env_dir
    log(f"  创建: {env_dir}")
    if dry_run:
        return env_dir
    try:
        venv.EnvBuilder(with_pip=True, clear=False).create(str(env_dir))
    except Exception as exc:  # noqa: BLE001
        log(f"  × 创建虚拟环境失败: {exc}")
        return None
    log("  √ 完成")
    return env_dir


def python_in(env_dir: Path) -> Path:
    if sys.platform == "win32":
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"


def install_app(env_dir: Path, kit_dir: Path, *, dry_run: bool) -> bool:
    step("3/5  安装 neobot-app")
    python = python_in(env_dir)
    wheelhouse = kit_dir / WHEELHOUSE_DIR

    if wheelhouse.is_dir() and any(wheelhouse.glob("*.whl")):
        log(f"  使用离线 wheelhouse: {wheelhouse}")
        args = ["--no-index", "--find-links", str(wheelhouse)]
    else:
        log("  未发现离线 wheelhouse，走 PyPI 安装（需要联网）")
        args = []

    code = run(
        [str(python), "-m", "pip", "install", "--upgrade", "neobot-app", *args],
        dry_run=dry_run,
    )
    if code != 0:
        log("  × 安装失败。若目标机器不能联网，请在有网的机器上先执行")
        log("    `python build_kit.py` 生成带 wheels/ 的离线包，再整体拷过来。")
        return False
    log("  √ 完成")
    return True


def write_env_file(data_dir: Path, *, dry_run: bool) -> None:
    env_path = data_dir / ".env"
    if env_path.exists():
        log(f"  已存在，保留: {env_path}")
        return
    log(f"  写入模板: {env_path}")
    if dry_run:
        return
    env_path.write_text(
        "# NeoBot 环境变量\n"
        "# 在这里填模型平台的地址与 API Key；也可以启动后在网页面板里填。\n"
        "# 例：\n"
        "# DeepSeek_URL=https://api.deepseek.com\n"
        "# DeepSeek_APIKey=sk-xxxx\n",
        encoding="utf-8",
    )


def write_start_script(target: Path, data_dir: Path, *, dry_run: bool) -> Path:
    log("  写启动脚本")
    if sys.platform == "win32":
        script = target / "start-neobot.bat"
        body = (
            "@echo off\r\n"
            "title NeoBot\r\n"
            f"set NEOBOT_DATA_DIR={data_dir}\r\n"
            f"set NEOBOT_ENV_FILE={data_dir}\\.env\r\n"
            f'cd /d "{target}"\r\n'
            f'"{python_in(target / "neobot-env")}" -m neobot_app.cli\r\n'
            "echo.\r\n"
            "echo ============================================================\r\n"
            "echo   NeoBot 已退出，上面是它最后的输出。\r\n"
            "echo   若是意外退出，把上面的报错内容发给 AI 让它看。\r\n"
            "echo ============================================================\r\n"
            "pause\r\n"
        )
    else:
        script = target / "start-neobot.sh"
        body = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f'export NEOBOT_DATA_DIR="{data_dir}"\n'
            f'export NEOBOT_ENV_FILE="{data_dir}/.env"\n'
            f'cd "{target}"\n'
            f'exec "{python_in(target / "neobot-env")}" -m neobot_app.cli\n'
        )
    if not dry_run:
        script.write_text(body, encoding="utf-8")
        if sys.platform != "win32":
            script.chmod(0o755)
    log(f"  √ {script.name}")
    return script


def setup_data(target: Path, *, dry_run: bool) -> Path:
    step("4/5  初始化数据目录")
    data_dir = target / "data"
    if data_dir.is_dir():
        log(f"  已存在，保留: {data_dir}")
    else:
        log(f"  创建: {data_dir}")
        if not dry_run:
            (data_dir / "plugins").mkdir(parents=True, exist_ok=True)
            (data_dir / "plugins_data").mkdir(parents=True, exist_ok=True)
    write_env_file(data_dir, dry_run=dry_run)
    write_start_script(target, data_dir, dry_run=dry_run)
    return data_dir


def setup_napcat(kit_dir: Path, target: Path, *, dry_run: bool, qq_path: str | None) -> None:
    step("5/5  NapCat 与 QQ 版本检查")
    napcat_src = kit_dir / NAPCAT_DIR
    if napcat_src.is_dir():
        dest = target / "napcat"
        if dest.exists():
            log(f"  已存在，保留: {dest}")
        else:
            log(f"  从分发包解压 NapCat: {napcat_src} -> {dest}")
            if not dry_run:
                shutil.copytree(napcat_src, dest)
    else:
        log("  分发包里没有 napcat/（跳过解压）")
        log("  可从 NapCat.Shell 的 release 下载后放进 napcat/ 再重跑本脚本")

    # 版本检查是这一步的重点：NapCat 是注入官方 QQNT 运行的，两边版本必须配套
    qq = detect_qq(qq_path)
    napcat_version = DEFAULT_NAPCAT_VERSION
    config = napcat_src / "config" / "version.txt" if napcat_src.is_dir() else None
    if config is not None and config.is_file():
        napcat_version = config.read_text(encoding="utf-8", errors="replace").strip() or napcat_version

    verdict = check_compat(napcat_version, qq)
    log()
    if verdict.level == "ok":
        log(f"  √ {verdict.message}")
    elif verdict.level == "mismatch":
        log(f"  !! {verdict.message}")
        log("     这是本步最重要的检查 —— 版本不匹配不会报错，只会表现为持续掉线。")
    else:
        log(f"  ? {verdict.message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="NeoBot 懒人安装器")
    parser.add_argument("--target", default="neobot", help="安装目录（默认 ./neobot）")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不做任何修改")
    parser.add_argument("--qq", default=None, help="QQ.exe 路径或 QQNT 安装目录（用于版本检查）")
    args = parser.parse_args()

    kit_dir = Path(__file__).resolve().parent
    target = Path(args.target).expanduser().resolve()

    log("=" * 66)
    log("NeoBot 懒人安装器")
    log("=" * 66)
    log(f"  分发包目录: {kit_dir}")
    log(f"  安装目录  : {target}")
    if args.dry_run:
        log("  （--dry-run：只打印计划，不修改任何文件）")

    if not check_python():
        return 2

    env_dir = make_venv(target, dry_run=args.dry_run)
    if env_dir is None:
        return 2

    if not install_app(env_dir, kit_dir, dry_run=args.dry_run):
        return 2

    setup_data(target, dry_run=args.dry_run)
    setup_napcat(kit_dir, target, dry_run=args.dry_run, qq_path=args.qq)

    step("完成")
    if sys.platform == "win32":
        log(f"  启动: {target / 'start-neobot.bat'}")
    else:
        log(f"  启动: {target / 'start-neobot.sh'}")
    log()
    log("  首次启动后打开网页面板，按「接入模型」教程填供应商与模型；")
    log("  出厂模型库是空的，需要自己接入 —— 面板会自动弹出教程。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
