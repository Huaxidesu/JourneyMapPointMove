"""配置读写与游戏目录识别。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / "config.json"

DEFAULTS: dict = {
    "journeymapDir": "",
    "gameDir": "",
    "inputType": "gameDir",
    "lastSource": "",
    "lastTargets": [],
    "defaultConflict": "skip",
    "backupDir": "backup",
    "lastSyncAt": "",
    "lastMode": "C",
}


def load() -> dict:
    """读取配置；文件缺失或内容损坏时返回默认值。"""
    if not CONFIG_FILE.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update({key: value for key, value in data.items() if key in DEFAULTS})
    return merged


def save(cfg: dict) -> None:
    """把配置写入入口同目录的 `config.json`。"""
    CONFIG_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def clean_input(raw: str) -> str:
    """去除拖放路径两侧的引号与空白。"""
    return raw.strip().strip('"').strip("'").strip()


def validate_journeymap(path: Path) -> bool:
    """目录内存在 `data/mp` 或 `data/sp` 时视为有效的 journeymap 目录。"""
    return (path / "data" / "mp").is_dir() or (path / "data" / "sp").is_dir()


def resolve(raw: str) -> tuple[Path | None, str]:
    """识别玩家输入的路径，返回 journeymap 目录与输入类型。

    按序尝试：游戏目录下的 `journeymap`、输入路径本身、输入路径下的 `.minecraft/journeymap`。
    无法识别时返回 `(None, "")`。
    """
    text = clean_input(raw)
    if not text:
        return None, ""
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        path = path.resolve()
    except OSError:
        return None, ""
    if not path.is_dir():
        return None, ""

    candidate = path / "journeymap"
    if validate_journeymap(candidate):
        return candidate, "gameDir"
    if validate_journeymap(path):
        return path, "journeymapDir"
    candidate = path / ".minecraft" / "journeymap"
    if validate_journeymap(candidate):
        return candidate, "gameDir"
    return None, ""


SKIP_DIRS = {
    "$Recycle.Bin",
    "System Volume Information",
    "Windows",
    "Program Files",
    "Program Files (x86)",
    "ProgramData",
    "node_modules",
    "__pycache__",
    "Temp",
    "Cache",
    "AppData",
}

PRIORITY_NAMES = (
    "journeymap",
    "minecraft",
    "gtnh",
    "hmcl",
    "prism",
    "multimc",
    "instance",
    "version",
)


def _priority(name: str) -> int:
    """游戏相关目录优先深入，避免在无关子树里耗尽遍历预算。"""
    lowered = name.lower()
    for index, keyword in enumerate(PRIORITY_NAMES):
        if keyword in lowered:
            return index
    return len(PRIORITY_NAMES)


def _candidate_roots() -> list[Path]:
    """收集值得搜索的常见游戏目录，按命中概率从高到低排列。"""
    home = Path.home()
    roots: list[Path] = []
    for relative in ("AppData/Roaming/.minecraft", ".minecraft"):
        path = home / relative
        if path.is_dir():
            roots.append(path)
    for drive in ("D", "E", "F", "C"):
        base = Path(f"{drive}:/")
        try:
            if not base.is_dir():
                continue
        except OSError:
            continue
        for name in ("Game", "Games", "Minecraft", "MC", "我的世界"):
            path = base / name
            if path.is_dir():
                roots.append(path)
    for relative in ("Desktop", "Documents", "Downloads", "Games"):
        path = home / relative
        if path.is_dir():
            roots.append(path)
    return roots


def discover(
    limit: int = 40,
    max_dirs: int = 12000,
    max_depth: int = 8,
    timeout: float = 5.0,
) -> list[Path]:
    """在常见游戏位置中自动搜索 `journeymap` 目录。

    收齐候选后再由 `rank_candidates` 排序；每个候选根目录独立计算遍历预算，
    并设总超时，避免某个大目录吃光全部时间。跳过系统目录与隐藏目录，
    限制深度，不跟随目录联接。
    """
    found: list[Path] = []
    seen: set[str] = set()
    deadline = time.monotonic() + timeout
    for root in _candidate_roots():
        if time.monotonic() > deadline:
            break
        scanned = 0
        base_depth = len(root.parts)
        for dirpath, dirnames, _files in os.walk(root, topdown=True):
            if time.monotonic() > deadline:
                break
            scanned += 1
            if scanned > max_dirs:
                break
            if len(Path(dirpath).parts) - base_depth >= max_depth:
                dirnames[:] = []
                continue
            dirnames[:] = [
                name
                for name in dirnames
                if (not name.startswith(".") or name.lower() == ".minecraft")
                and not name.startswith("$")
                and name not in SKIP_DIRS
            ]
            dirnames.sort(key=_priority)
            candidate = Path(dirpath) / "journeymap"
            if validate_journeymap(candidate):
                key = str(candidate).lower()
                if key not in seen:
                    seen.add(key)
                    found.append(candidate)
                dirnames[:] = [name for name in dirnames if name != "journeymap"]
    return found[:limit]


def waypoint_count(path: Path) -> int:
    """统计某个 journeymap 目录下的标点文件数，用于给候选目录排序。"""
    total = 0
    for space in ("mp", "sp"):
        base = path / "data" / space
        if not base.is_dir():
            continue
        for route_dir in base.iterdir():
            if not route_dir.is_dir():
                continue
            waypoints = route_dir / "waypoints"
            if waypoints.is_dir():
                total += sum(1 for _ in waypoints.glob("*.json"))
    return total


def activity(path: Path) -> float:
    """估算目录最近被游戏使用的时间，用于把当前在用的客户端排到最前。

    只读取 `journeymap` 直属条目与各线路目录的时间戳，不递归遍历地图瓦片。
    """
    timestamps = [path.stat().st_mtime]
    for child in path.iterdir():
        try:
            timestamps.append(child.stat().st_mtime)
        except OSError:
            continue
    for space in ("mp", "sp"):
        base = path / "data" / space
        if not base.is_dir():
            continue
        for route_dir in base.iterdir():
            try:
                timestamps.append(route_dir.stat().st_mtime)
            except OSError:
                continue
            waypoints = route_dir / "waypoints"
            if waypoints.is_dir():
                try:
                    timestamps.append(waypoints.stat().st_mtime)
                except OSError:
                    continue
    return max(timestamps)


def rank_candidates(
    paths: list[Path], limit: int = 5, max_age_days: int = 60
) -> list[Path]:
    """最近在用的目录排在最前，并过滤长期未使用的旧版本。

    过滤后若结果为空，仍保留活跃度最高的一个，保证玩家总有默认值。
    """
    scored = [(activity(path), waypoint_count(path), path) for path in paths]
    scored.sort(key=lambda item: (-item[0], -item[1], str(item[2]).lower()))
    cutoff = time.time() - max_age_days * 86400
    recent = [item for item in scored if item[0] >= cutoff]
    if not recent:
        recent = scored[:1]
    return [item[2] for item in recent[:limit]]


def backup_root(cfg: dict) -> Path:
    """返回备份根目录；相对路径按入口目录解析。"""
    path = Path(cfg.get("backupDir") or "backup")
    if not path.is_absolute():
        path = ROOT / path
    return path
