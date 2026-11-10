"""扫描 JourneyMap 的线路目录与标点文件。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Route, Waypoint

UUID_TAIL = re.compile(
    r"_([0-9a-fA-F]{8}~[0-9a-fA-F]{4}~[0-9a-fA-F]{4}~[0-9a-fA-F]{4}~[0-9a-fA-F]{12})$"
)


def parse_name(name: str) -> tuple[str, str | None]:
    """把目录名拆为线路标识与世界 UUID；UUID 中的 `~` 还原为 `-`。"""
    match = UUID_TAIL.search(name)
    if not match:
        return name, None
    return name[: match.start()], match.group(1).replace("~", "-")


def read_waypoint(path: Path) -> Waypoint:
    """读取标点 JSON；解析失败时仍按文件名登记，保证可搬运。"""
    stem = path.stem
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        dimensions = tuple(int(value) for value in data.get("dimensions", []))
        name = str(data.get("name") or stem)
        return Waypoint(
            path=path,
            wp_id=stem,
            name=name,
            dimensions=dimensions,
            valid=True,
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return Waypoint(path=path, wp_id=stem, name=stem, valid=False)


def scan(journeymap_dir: Path) -> list[Route]:
    """扫描 `data/mp` 与 `data/sp`，只读，不修改任何文件。"""
    routes: list[Route] = []
    data_dir = journeymap_dir / "data"
    for space in ("mp", "sp"):
        base = data_dir / space
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir(), key=lambda item: item.name.lower()):
            if not child.is_dir():
                continue
            label, world_uuid = parse_name(child.name)
            waypoints_dir = child / "waypoints"
            waypoints: list[Waypoint] = []
            if waypoints_dir.is_dir() and not waypoints_dir.is_junction():
                for path in sorted(waypoints_dir.glob("*.json")):
                    waypoints.append(read_waypoint(path))
            elif waypoints_dir.is_junction():
                try:
                    for path in sorted(waypoints_dir.glob("*.json")):
                        waypoints.append(read_waypoint(path))
                except OSError:
                    pass
            try:
                mtime = waypoints_dir.stat().st_mtime if waypoints_dir.exists() else 0.0
            except OSError:
                mtime = 0.0
            routes.append(
                Route(
                    path=child,
                    name=child.name,
                    label=label,
                    world_uuid=world_uuid,
                    space=space,
                    waypoints_dir=waypoints_dir,
                    waypoints=waypoints,
                    mtime=mtime,
                    is_junction=waypoints_dir.is_junction(),
                )
            )
    return routes


def group(routes: list[Route]) -> dict[str, list[Route]]:
    """按世界 UUID 分组，保持线路原有顺序。"""
    result: dict[str, list[Route]] = {}
    for route in routes:
        result.setdefault(route.group_key, []).append(route)
    return result
