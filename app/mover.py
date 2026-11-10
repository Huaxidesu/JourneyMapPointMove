"""变更计划、备份、搬运、回滚与目录联接。"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

from . import config as cfgmod
from .models import Plan, PlanItem, Route, Waypoint

CONFLICT_LABELS = {
    "skip": "跳过",
    "overwrite": "覆盖",
    "keepBoth": "两者都保留",
}
MODE_LABELS = {
    "A": "单线搬运",
    "B": "合并到主线路",
    "C": "全线路同步",
    "D": "实时共享",
}


def sha1(path: Path) -> str:
    """计算文件的 SHA-1。"""
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def union(sources: list[Route]) -> list[tuple[Route, Waypoint]]:
    """按去重键取标点并集，保持首次出现的顺序。"""
    seen: set[str] = set()
    result: list[tuple[Route, Waypoint]] = []
    for route in sources:
        for waypoint in route.waypoints:
            if waypoint.key in seen:
                continue
            seen.add(waypoint.key)
            result.append((route, waypoint))
    return result


def _new_id(base: str, taken: set[str]) -> str:
    index = 2
    while f"{base}_dup{index}" in taken:
        index += 1
    return f"{base}_dup{index}"


def build_plan(
    mode: str, sources: list[Route], targets: list[Route], conflict: str
) -> Plan:
    """生成完整变更计划，不执行任何写操作。"""
    pool = union(sources)
    plan = Plan(mode=mode, conflict=conflict, targets=list(targets))
    for dst in targets:
        existing = {waypoint.key for waypoint in dst.waypoints}
        taken = set(existing)
        for src, waypoint in pool:
            if waypoint.key in existing:
                if conflict == "skip":
                    plan.items.append(
                        PlanItem(
                            src=src,
                            dst=dst,
                            src_file=waypoint.path,
                            dst_file=dst.waypoints_dir / f"{waypoint.key}.json",
                            action="skip",
                            reason="目标已存在同名标点",
                        )
                    )
                elif conflict == "overwrite":
                    plan.items.append(
                        PlanItem(
                            src=src,
                            dst=dst,
                            src_file=waypoint.path,
                            dst_file=dst.waypoints_dir / f"{waypoint.key}.json",
                            action="overwrite",
                            reason="覆盖同名标点",
                        )
                    )
                else:
                    new_id = _new_id(waypoint.key, taken)
                    taken.add(new_id)
                    plan.items.append(
                        PlanItem(
                            src=src,
                            dst=dst,
                            src_file=waypoint.path,
                            dst_file=dst.waypoints_dir / f"{new_id}.json",
                            action="rename",
                            reason="保留两份",
                            new_id=new_id,
                        )
                    )
            else:
                taken.add(waypoint.key)
                plan.items.append(
                    PlanItem(
                        src=src,
                        dst=dst,
                        src_file=waypoint.path,
                        dst_file=dst.waypoints_dir / f"{waypoint.key}.json",
                        action="copy",
                        reason="目标缺少该标点",
                    )
                )
    return plan


def _rewrite_id(path: Path, new_id: str) -> None:
    """「两者都保留」时同步修改 JSON 的 `id`，保持与文件名一致。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    data["id"] = new_id
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def execute(plan: Plan) -> int:
    """执行计划，返回实际写入的文件数。"""
    written = 0
    for item in plan.items:
        if item.action == "skip":
            continue
        item.dst.waypoints_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item.src_file, item.dst_file)
        if item.action == "rename" and item.new_id:
            _rewrite_id(item.dst_file, item.new_id)
        written += 1
    return written


def backup(routes: list[Route], cfg: dict, mode: str, note: str = "") -> Path:
    """备份涉及的 `waypoints` 目录，并写 `manifest.json`。"""
    root = cfgmod.backup_root(cfg)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = root / stamp
    suffix = 1
    while dest.exists():
        dest = root / f"{stamp}-{suffix}"
        suffix += 1
    dest.mkdir(parents=True)

    entries: list[dict] = []
    for route in routes:
        relative = Path(route.space) / route.name / "waypoints"
        snapshot = dest / relative
        was_junction = route.waypoints_dir.is_junction()
        files: list[dict] = []
        if route.waypoints_dir.is_dir():
            try:
                shutil.copytree(route.waypoints_dir, snapshot, dirs_exist_ok=True)
            except OSError:
                snapshot.mkdir(parents=True, exist_ok=True)
            for path in sorted(snapshot.glob("*.json")):
                files.append({"path": path.name, "sha1": sha1(path)})
        entries.append(
            {
                "name": route.name,
                "space": route.space,
                "waypointsDir": str(route.waypoints_dir),
                "wasJunction": was_junction,
                "files": files,
            }
        )

    manifest = {
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "note": note,
        "journeymapDir": str(cfg.get("journeymapDir", "")),
        "routes": entries,
    }
    (dest / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return dest


def list_backups(cfg: dict) -> list[Path]:
    """按时间倒序列出含 `manifest.json` 的备份目录。"""
    root = cfgmod.backup_root(cfg)
    if not root.is_dir():
        return []
    return sorted(
        (path for path in root.iterdir() if (path / "manifest.json").is_file()),
        key=lambda path: path.name,
        reverse=True,
    )


def rollback(stamp: str, cfg: dict) -> int:
    """按备份时间点整体还原，并校验文件哈希。"""
    dest = cfgmod.backup_root(cfg) / stamp
    manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    restored = 0
    for entry in manifest["routes"]:
        waypoints_dir = Path(entry["waypointsDir"])
        if waypoints_dir.is_junction():
            try:
                waypoints_dir.rmdir()
            except OSError:
                pass
        if waypoints_dir.is_dir():
            for path in waypoints_dir.glob("*.json"):
                path.unlink()
        snapshot = dest / entry["space"] / entry["name"] / "waypoints"
        if snapshot.is_dir():
            waypoints_dir.mkdir(parents=True, exist_ok=True)
            for path in sorted(snapshot.glob("*.json")):
                shutil.copy2(path, waypoints_dir / path.name)
                restored += 1
        for record in entry.get("files", []):
            target = waypoints_dir / record["path"]
            if not target.is_file() or sha1(target) != record["sha1"]:
                raise RuntimeError(f"回滚校验失败：{entry['name']}/{record['path']}")
    return restored


def shared_dir(group_key: str) -> Path:
    """返回分组共享目录；位置在工具目录内，不写入 journeymap 数据目录。"""
    safe = re.sub(r"[^0-9A-Za-z_-]", "_", group_key)
    return cfgmod.ROOT / "shared" / safe / "waypoints"


def create_junction(link: Path, target: Path) -> None:
    """创建 Windows 目录联接。"""
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 or not link.is_junction():
        detail = (result.stdout or "") + (result.stderr or "")
        raise RuntimeError(f"创建目录联接失败：{detail.strip()}")


def setup_junction(routes: list[Route]) -> Path:
    """把同组各线路的 `waypoints` 指向同一共享目录。"""
    keys = {route.group_key for route in routes}
    if len(keys) != 1:
        raise ValueError("目录联接仅允许同一世界 UUID 分组内的线路")
    key = next(iter(keys))
    if key.startswith("UNKNOWN:"):
        raise ValueError("世界身份未知的线路不能建立目录联接")

    shared = shared_dir(key)
    shared.mkdir(parents=True, exist_ok=True)
    for _src, waypoint in union(routes):
        target = shared / f"{waypoint.key}.json"
        if not target.exists():
            shutil.copy2(waypoint.path, target)

    for route in routes:
        waypoints_dir = route.waypoints_dir
        if waypoints_dir.is_junction():
            waypoints_dir.rmdir()
        elif waypoints_dir.is_dir():
            shutil.rmtree(waypoints_dir)
        waypoints_dir.parent.mkdir(parents=True, exist_ok=True)
        create_junction(waypoints_dir, shared)
    return shared


def check_junctions(routes: list[Route]) -> list[tuple[Route, bool]]:
    """检查各线路的共享链接是否有效。"""
    result: list[tuple[Route, bool]] = []
    for route in routes:
        valid = route.waypoints_dir.is_junction() and route.waypoints_dir.exists()
        result.append((route, valid))
    return result


def repair_junctions(routes: list[Route]) -> int:
    """修复断链或被覆盖的共享目录，返回修复数量。"""
    fixed = 0
    for route in routes:
        shared = shared_dir(route.group_key)
        waypoints_dir = route.waypoints_dir
        if waypoints_dir.is_junction() and waypoints_dir.exists():
            continue
        if waypoints_dir.is_junction():
            waypoints_dir.rmdir()
        elif waypoints_dir.is_dir():
            shared.mkdir(parents=True, exist_ok=True)
            for path in waypoints_dir.glob("*.json"):
                target = shared / path.name
                if not target.exists():
                    shutil.copy2(path, target)
            shutil.rmtree(waypoints_dir)
        waypoints_dir.parent.mkdir(parents=True, exist_ok=True)
        create_junction(waypoints_dir, shared)
        fixed += 1
    return fixed


def export_backup_zip(cfg: dict) -> Path | None:
    """把备份目录打包为 zip，便于玩家另行保存。"""
    root = cfgmod.backup_root(cfg)
    if not root.is_dir():
        return None
    output = cfgmod.ROOT / f"标点备份-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(root))
    return output
