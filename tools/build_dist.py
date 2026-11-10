"""组装发布包：准备 Python embeddable 运行时、复制源码并生成压缩包。"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST_ROOT = ROOT / "dist"
PACKAGE = DIST_ROOT / "JourneyMapPointMove"
DEFAULT_PYTHON_VERSION = "3.13.1"


def runtime_url(version: str) -> str:
    return (
        f"https://www.python.org/ftp/python/{version}/"
        f"python-{version}-embed-amd64.zip"
    )


def download_runtime(version: str, destination: Path) -> None:
    """下载并解压 Python embeddable 运行时，网络超时设为 30 秒。"""
    url = runtime_url(version)
    cache_dir = ROOT / "tmp"
    cache_dir.mkdir(parents=True, exist_ok=True)
    archive = cache_dir / f"python-{version}-embed-amd64.zip"
    if archive.is_file() and archive.stat().st_size > 0:
        print(f"使用已缓存的运行时：{archive}")
    else:
        print(f"下载运行时：{url}")
        with urllib.request.urlopen(url, timeout=30) as response:
            with archive.open("wb") as handle:
                shutil.copyfileobj(response, handle)
        print(f"下载完成：{archive.stat().st_size} 字节")
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(destination)


def assemble(offline: bool, version: str) -> Path:
    if PACKAGE.exists():
        shutil.rmtree(PACKAGE)
    PACKAGE.mkdir(parents=True)

    shutil.copy2(ROOT / "旅行地图标点搬运.bat", PACKAGE / "旅行地图标点搬运.bat")
    shutil.copytree(
        ROOT / "app",
        PACKAGE / "app",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copy2(ROOT / "使用说明.md", PACKAGE / "使用说明.md")
    shutil.copy2(ROOT / "README.md", PACKAGE / "README.md")
    shutil.copy2(ROOT / "LICENSE", PACKAGE / "LICENSE")

    python_dir = PACKAGE / "python"
    local_runtime = ROOT / "python"
    if local_runtime.is_dir() and (local_runtime / "python.exe").is_file():
        print(f"复制仓库内的运行时：{local_runtime}")
        shutil.copytree(local_runtime, python_dir)
    elif offline:
        python_dir.mkdir(parents=True)
        print("离线模式：已跳过运行时，发布的包需自行放入 python/ 后使用。")
    else:
        download_runtime(version, python_dir)
    return PACKAGE


def make_archive(package: Path, use_7z: bool) -> Path:
    """按指定格式生成压缩包；7z 不可用或指定 zip 时回退到 zip。"""
    seven_zip = shutil.which("7z") if use_7z else None
    if seven_zip:
        output = DIST_ROOT / "JourneyMapPointMove.7z"
        result = subprocess.run(
            [seven_zip, "a", "-t7z", "-y", str(output), str(package)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"7z 打包失败：{result.stdout}{result.stderr}")
        return output

    output = DIST_ROOT / "JourneyMapPointMove.zip"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                target = Path("JourneyMapPointMove") / path.relative_to(package)
                archive.write(path, target)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="组装 JourneyMapPointMove 发布包")
    parser.add_argument("--offline", action="store_true", help="不下载 Python 运行时")
    parser.add_argument("--version", default=DEFAULT_PYTHON_VERSION, help="Python 版本")
    parser.add_argument("--no-archive", action="store_true", help="只生成目录，不压缩")
    parser.add_argument(
        "--format", choices=["auto", "7z", "zip"], default="auto", help="压缩包格式"
    )
    args = parser.parse_args()

    if not (ROOT / "使用说明.md").is_file():
        print("缺少 使用说明.md，无法组装发布包。")
        return 1
    package = assemble(args.offline, args.version)
    print(f"发布目录：{package}")
    if args.no_archive:
        return 0
    use_7z = args.format == "7z" or (
        args.format == "auto" and shutil.which("7z") is not None
    )
    output = make_archive(package, use_7z)
    print(f"发布压缩包：{output}（{output.stat().st_size} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
