"""线路、标点与变更计划的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Waypoint:
    """一个标点文件。去重键取文件名去掉扩展名，与 JourneyMap 的 `id` 一致。"""

    path: Path
    wp_id: str
    name: str
    dimensions: tuple[int, ...] = ()
    valid: bool = True

    @property
    def key(self) -> str:
        return self.wp_id


@dataclass
class Route:
    """一条线路目录。`space` 取 `mp` 或 `sp`。"""

    path: Path
    name: str
    label: str
    world_uuid: str | None
    space: str
    waypoints_dir: Path
    waypoints: list[Waypoint] = field(default_factory=list)
    mtime: float = 0.0
    is_junction: bool = False

    @property
    def group_key(self) -> str:
        """同一世界 UUID 归为一组；无 UUID 的目录各自独立。"""
        if self.world_uuid:
            return self.world_uuid
        return f"UNKNOWN:{self.space}:{self.name}"

    @property
    def dimension_set(self) -> set[int]:
        result: set[int] = set()
        for waypoint in self.waypoints:
            result.update(waypoint.dimensions)
        return result


@dataclass
class PlanItem:
    """一条待执行的文件操作。"""

    src: Route
    dst: Route
    src_file: Path
    dst_file: Path
    action: str
    reason: str = ""
    new_id: str | None = None


@dataclass
class Plan:
    """一次搬运或同步的完整计划。"""

    mode: str
    conflict: str
    items: list[PlanItem] = field(default_factory=list)
    targets: list[Route] = field(default_factory=list)

    def count(self, action: str) -> int:
        return sum(1 for item in self.items if item.action == action)

    @property
    def writable_count(self) -> int:
        return sum(1 for item in self.items if item.action != "skip")
