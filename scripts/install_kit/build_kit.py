"""构建 NeoBot 懒人安装包（离线分发包）。

在有网的机器上跑：

    python build_kit.py                    # 产出 dist/neobot-kit-<日期>.zip
    python build_kit.py --napcat-zip X.zip # 用本地已下好的 NapCat 包
    python build_kit.py --skip-wheels      # 不收集依赖（目标机器需联网）

产出目录结构：

    neobot-kit/
      install.py          # 目标机器上跑这个
      qq_version.py       # QQ/NapCat 版本匹配检查
      wheels/             # neobot-app 及其依赖的离线 wheel
      napcat/             # NapCat.Shell 解压后的内容
      README.md

为什么要把依赖也打进去
----------------------
目标机器往往没装编译工具链，`onnxruntime` / `cryptography` 这类包
在没有 wheel 时源码编译会失败一大片。提前在本机把 wheel 收齐，
目标机器纯离线装，成功率最高。

NapCat 的下载源
---------------
NapCat.Shell 发布在 GitHub Releases 上。若目标网络访问 GitHub 不稳定
（本会话实测该网络下 github.com:443 时通时断），可以用 `--mirror` 指定代理前缀，
例如 `--mirror https://ghproxy.net/`。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIST = HERE.parent.parent / "dist"

#: NapCat.Shell 的 release 下载地址（版本与 QQ 的配套关系见 qq_version.py）
NAPCAT_VERSION = "v4.18.28"
NAPCAT_URL = (
    "https://github.com/NapNeko/NapCatQQ/releases/download/"
    f"{NAPCAT_VERSION}/NapCat.Shell.zip"
)


def log(message: str = "") -> None:
    print(message, flush=True)


def collect_wheels(dest: Path) -> bool:
    """把 neobot-app 及其全部依赖下成 wheel。"""
    log(f"收集依赖 wheel -> {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    code = subprocess.run(
        [
            sys.executable, "-m", "pip", "download",
            "--dest", str(dest),
            "--only-binary", ":all:",   # 只要 wheel，避免下到源码包还得在目标机编译
            "neobot-app",
        ]
    ).returncode
    if code != 0:
        log("  × 收集失败。请检查网络，或改用 --skip-wheels。")
        return False
    count = len(list(dest.glob("*.whl")))
    log(f"  √ 共 {count} 个 wheel")
    return True


def fetch_napcat(dest: Path, *, napcat_zip: str | None, mirror: str) -> bool:
    """取得 NapCat.Shell 并解压到 dest。"""
    dest.mkdir(parents=True, exist_ok=True)
    if napcat_zip:
        archive = Path(napcat_zip)
        if not archive.is_file():
            log(f"  × 指定的 NapCat 包不存在: {archive}")
            return False
        log(f"使用本地 NapCat 包: {archive}")
    else:
        url = f"{mirror}{NAPCAT_URL}" if mirror else NAPCAT_URL
        archive = Path(tempfile.gettempdir()) / "NapCat.Shell.zip"
        log(f"下载 NapCat.Shell {NAPCAT_VERSION}")
        log(f"  {url}")
        try:
            urllib.request.urlretrieve(url, archive)  # noqa: S310
        except Exception as exc:  # noqa: BLE001
            log(f"  × 下载失败: {exc}")
            log("    可用 --napcat-zip 指定本地已下好的包，或用 --mirror 换代理。")
            return False

    try:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    except Exception as exc:  # noqa: BLE001
        log(f"  × 解压失败: {exc}")
        return False
    log(f"  √ 已解压到 {dest}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 NeoBot 懒人安装包")
    parser.add_argument("--out", default=None, help="输出目录（默认仓库根下的 dist/）")
    parser.add_argument("--napcat-zip", default=None, help="本地已有的 NapCat.Shell.zip")
    parser.add_argument("--mirror", default="", help="下载代理前缀，如 https://ghproxy.net/")
    parser.add_argument("--skip-wheels", action="store_true", help="不收集依赖 wheel")
    parser.add_argument("--skip-napcat", action="store_true", help="不下载 NapCat")
    args = parser.parse_args()

    stage = Path(args.out).resolve() if args.out else DIST / "neobot-kit"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)

    log("=" * 66)
    log("构建 NeoBot 懒人安装包")
    log("=" * 66)
    log(f"  暂存目录: {stage}")

    log()
    log("── 复制安装脚本 ──")
    for name in ("install.py", "qq_version.py"):
        shutil.copy2(HERE / name, stage / name)
        log(f"  √ {name}")
    readme = HERE / "README.md"
    if readme.is_file():
        shutil.copy2(readme, stage / "README.md")
        log("  √ README.md")

    ok = True
    if not args.skip_wheels:
        log()
        log("── 收集依赖 ──")
        ok = collect_wheels(stage / "wheels") and ok
    if not args.skip_napcat:
        log()
        log("── 获取 NapCat ──")
        ok = fetch_napcat(stage / "napcat", napcat_zip=args.napcat_zip, mirror=args.mirror) and ok

    log()
    log("── 打 zip ──")
    zip_path = stage.parent / f"neobot-kit-{date.today():%Y%m%d}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(stage.rglob("*")):
            if item.is_file():
                zf.write(item, item.relative_to(stage.parent))
    size_mb = zip_path.stat().st_size / 1024 / 1024
    log(f"  √ {zip_path}  ({size_mb:.1f} MB)")

    log()
    if not ok:
        log("有步骤失败 —— 上面每一条都写了原因，修好后重跑即可（已完成的会复用）。")
    log("把 zip 拷到目标机器，解压后运行：python install.py")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
