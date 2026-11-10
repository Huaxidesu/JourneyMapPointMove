"""生成自给自足的只读测试夹具，不依赖任何本机客户端目录。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tmp" / "fixture" / "journeymap"

# 虚构世界 UUID 与线路名，仅用于验证目录名解析、分组与搬运逻辑。
MAIN_WORLD_TILDE = "a1b2c3d4~1111~2222~3333~444455556666"
MAIN_WORLD_UUID = "a1b2c3d4-1111-2222-3333-444455556666"
OTHER_WORLD_TILDE = "b2c3d4e5~1111~2222~3333~444455556666"
THIRD_WORLD_TILDE = "c3d4e5f6~1111~2222~3333~444455556666"

SOURCE_ROUTE = "~Local_" + MAIN_WORLD_TILDE
TARGET_ROUTE = "example.net_" + MAIN_WORLD_TILDE

# 8 条多人线路：同一世界对应三条，另有不同世界与无 UUID 的目录。
MULTI_ROUTES = (
    "example.net",
    "example.net_" + OTHER_WORLD_TILDE,
    "example.net_" + MAIN_WORLD_TILDE,
    "mc1.example.net",
    "mc1.example.net_" + MAIN_WORLD_TILDE,
    "~Local_" + OTHER_WORLD_TILDE,
    "~Local_" + THIRD_WORLD_TILDE,
    SOURCE_ROUTE,
)

WAYPOINT_COUNT = 21


def _waypoint(index: int) -> tuple[str, dict]:
    """构造一个结构完整的虚构标点。"""
    name = f"标点{index:02d}"
    x, y, z = index * 16, 64, -index * 8
    stem = f"{name}_{x},{y},{z}"
    data = {
        "id": stem,
        "name": name,
        "icon": "waypoint-normal.png",
        "x": x,
        "y": y,
        "z": z,
        "r": 160 + index % 60,
        "g": 140 + index % 40,
        "b": 200 + index % 30,
        "enable": True,
        "type": "Normal",
        "origin": "JourneyMap",
        "dimensions": [0],
    }
    return stem, data


def _write_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def build() -> Path:
    """生成线路目录结构与标点文件，不读取任何真实客户端数据。"""
    if FIXTURE.exists():
        shutil.rmtree(FIXTURE)
    multi = FIXTURE / "data" / "mp"
    multi.mkdir(parents=True)

    for name in MULTI_ROUTES:
        waypoints = multi / name / "waypoints"
        waypoints.mkdir(parents=True)
        (multi / name / "DIM0").mkdir()
        if name == SOURCE_ROUTE:
            for index in range(1, WAYPOINT_COUNT + 1):
                stem, data = _waypoint(index)
                _write_json(waypoints / f"{stem}.json", data)

    single = FIXTURE / "data" / "sp" / "测试单人世界" / "waypoints"
    single.mkdir(parents=True)
    _write_json(
        single / "家_0,64,0.json",
        {
            "id": "家_0,64,0",
            "name": "家",
            "icon": "waypoint-normal.png",
            "x": 0,
            "y": 64,
            "z": 0,
            "r": 200,
            "g": 200,
            "b": 200,
            "enable": True,
            "type": "Normal",
            "origin": "JourneyMap",
            "dimensions": [0],
        },
    )
    return FIXTURE


if __name__ == "__main__":
    print(build())
