"""端到端自测：在 tmp/ 的夹具上验证全部功能，不触碰真实客户端。"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from app import config as cfgmod, mover, scanner  # noqa: E402
from make_fixture import (  # noqa: E402
    MAIN_WORLD_TILDE,
    MAIN_WORLD_UUID,
    TARGET_ROUTE,
    build as build_fixture,
)

PY = sys.executable
FAILS: list[str] = []
FIXTURE: Path | None = None


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"  [通过] {message}")
    else:
        print(f"  [失败] {message}")
        FAILS.append(message)


def fresh(name: str) -> Path:
    """复制一份独立夹具，避免用例之间相互影响。"""
    destination = ROOT / "tmp" / f"case-{name}"
    if destination.exists():
        remove_tree(destination)
    shutil.copytree(FIXTURE, destination)
    return destination


def remove_tree(path: Path) -> None:
    """先移除目录联接，再删除目录树，避免跟随链接删除共享数据。"""
    if not path.exists():
        return
    for candidate in path.rglob("waypoints"):
        if candidate.is_junction():
            try:
                candidate.rmdir()
            except OSError:
                pass
    shutil.rmtree(path, ignore_errors=True)


def cfg_for(case: Path) -> dict:
    cfg = dict(cfgmod.DEFAULTS)
    cfg["journeymapDir"] = str(case)
    cfg["backupDir"] = str(ROOT / "tmp" / "backups" / case.name)
    return cfg


def main_routes(case: Path) -> list:
    return [
        route
        for route in scanner.scan(case)
        if route.world_uuid == MAIN_WORLD_UUID
    ]


def run_cli(
    case: Path, *arguments: str, stdin_text: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, "-m", "app.main", "--jm-dir", str(case), *arguments],
        cwd=ROOT,
        input=stdin_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def test_paths() -> None:
    print("\n[1] 路径识别")
    direct, kind = cfgmod.resolve(str(FIXTURE))
    check(direct == FIXTURE and kind == "journeymapDir", "journeymap 目录直接识别")
    game, kind = cfgmod.resolve(str(FIXTURE.parent))
    check(game == FIXTURE and kind == "gameDir", "游戏目录识别")
    wrapper = ROOT / "tmp" / "wrapper"
    (wrapper / ".minecraft" / "journeymap" / "data" / "mp").mkdir(
        parents=True, exist_ok=True
    )
    nested, kind = cfgmod.resolve(str(wrapper))
    check(
        nested == wrapper / ".minecraft" / "journeymap" and kind == "gameDir",
        ".minecraft 目录识别",
    )
    invalid, _ = cfgmod.resolve(str(ROOT / "tmp" / "不存在"))
    check(invalid is None, "无效路径返回 None")
    found = cfgmod.discover(limit=10, max_dirs=2000, timeout=2.0)
    check(isinstance(found, list), "自动搜索返回列表")
    check(
        all(cfgmod.validate_journeymap(path) for path in found),
        "自动搜索结果均为有效 journeymap 目录",
    )


def test_scan() -> None:
    print("\n[2] 扫描与分组")
    routes = scanner.scan(FIXTURE)
    check(len(routes) == 9, "共 9 条线路（8 条多人 + 1 条单人）")
    group = main_routes(FIXTURE)
    check(len(group) == 3, "主世界组含 3 条线路")
    check(sum(len(route.waypoints) for route in group) == 21, "组内共 21 个标点")
    check(
        scanner.parse_name(f"mc1.example.net_{MAIN_WORLD_TILDE}")[1]
        == MAIN_WORLD_UUID,
        "世界 UUID 解析正确",
    )
    check(scanner.parse_name("mc1.example.net")[1] is None, "无 UUID 目录识别为未知")


def test_c_mode_and_rollback() -> None:
    print("\n[3] C 模式全线路同步与回滚")
    case = fresh("c-mode")
    cfg = cfg_for(case)
    group = main_routes(case)
    source = [route for route in group if route.waypoints]
    check(len(source) == 1 and len(source[0].waypoints) == 21, "仅一条线路含 21 个标点")
    plan = mover.build_plan("C", group, group, "skip")
    check(plan.count("copy") == 42, "两条空线路各新增 21 个")
    check(plan.count("skip") == 21, "源线路已有 21 个被跳过")
    snapshot = mover.backup(group, cfg, "C")
    written = mover.execute(plan)
    check(written == 42, "实际写入 42 个文件")
    for route in group:
        check(
            len(list(route.waypoints_dir.glob("*.json"))) == 21,
            f"{route.label} 现有 21 个标点",
        )
    hashes = {
        mover.sha1(path)
        for route in group
        for path in route.waypoints_dir.glob("*.json")
    }
    check(len(hashes) == 21, "三条线路内容一致（21 个唯一哈希）")
    mover.rollback(snapshot.name, cfg)
    after = [len(list(route.waypoints_dir.glob("*.json"))) for route in group]
    check(after == [0, 0, 21], "回滚后恢复到 0 / 0 / 21")


def test_conflicts() -> None:
    print("\n[4] 三种冲突策略")
    for strategy in ("skip", "overwrite", "keepBoth"):
        case = fresh(f"conflict-{strategy}")
        group = main_routes(case)
        source = [route for route in group if route.waypoints][0]
        target_name = TARGET_ROUTE
        conflict_file = case / "data" / "mp" / target_name / "waypoints" / (
            source.waypoints[0].key + ".json"
        )
        data = json.loads(source.waypoints[0].path.read_text(encoding="utf-8"))
        data["r"] = 9
        conflict_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        group = main_routes(case)
        source = [route for route in group if len(route.waypoints) == 21][0]
        target = [route for route in group if route.name == target_name][0]
        plan = mover.build_plan("A", [source], [target], strategy)
        mover.execute(plan)
        files = sorted(target.waypoints_dir.glob("*.json"))
        if strategy == "skip":
            check(len(files) == 21, "skip：目标共 21 个文件")
            check(
                json.loads(conflict_file.read_text(encoding="utf-8"))["r"] == 9,
                "skip：原有文件保持不变",
            )
        elif strategy == "overwrite":
            check(len(files) == 21, "overwrite：目标共 21 个文件")
            check(
                json.loads(conflict_file.read_text(encoding="utf-8"))["r"] != 9,
                "overwrite：同名文件被源文件替换",
            )
        else:
            check(len(files) == 22, "keepBoth：目标共 22 个文件")
            renamed = [path for path in files if "_dup2" in path.stem]
            check(len(renamed) == 1, "keepBoth：生成 _dup2 文件")
            if renamed:
                content = json.loads(renamed[0].read_text(encoding="utf-8"))
                check(content["id"] == renamed[0].stem, "keepBoth：新文件 id 与文件名一致")


def test_junction() -> None:
    print("\n[5] D 模式目录联接、实时共享与修复")
    case = fresh("junction")
    cfg = cfg_for(case)
    group = main_routes(case)
    mover.backup(group, cfg, "D")
    shared = mover.setup_junction(group)
    check(len(list(shared.glob("*.json"))) == 21, "共享目录含 21 个标点")
    check(all(route.waypoints_dir.is_junction() for route in group), "三条线路均为目录联接")
    probe = shared / "探针_1,2,3.json"
    probe.write_text(
        json.dumps({"id": "探针_1,2,3", "name": "探针", "dimensions": [0]}) + "\n",
        encoding="utf-8",
    )
    check(
        all((route.waypoints_dir / probe.name).is_file() for route in group),
        "新增标点在全部线路实时可见",
    )
    broken = group[0].waypoints_dir
    broken.rmdir()
    broken.mkdir()
    check(not broken.is_junction(), "已模拟链接失效")
    fixed = mover.repair_junctions([group[0]])
    check(fixed == 1 and broken.is_junction(), "失效链接修复成功")
    for route in group:
        if route.waypoints_dir.is_junction():
            route.waypoints_dir.rmdir()
    shutil.rmtree(ROOT / "shared", ignore_errors=True)


def test_cli() -> None:
    print("\n[6] 命令行端到端")
    case = fresh("cli")
    result = run_cli(case, "--list")
    check(result.returncode == 0 and "线路清单" in result.stdout, "--list 正常")
    result = run_cli(case, "--mode", "C", "--yes", "--conflict", "skip")
    check(result.returncode == 0 and "完成" in result.stdout, "--mode C 静默执行成功")
    group = main_routes(case)
    check(
        all(len(list(route.waypoints_dir.glob("*.json"))) == 21 for route in group),
        "CLI 同步后三条线路各 21 个标点",
    )
    auto_case = fresh("auto")
    result = run_cli(auto_case, "--auto")
    check(result.returncode == 0 and "完成" in result.stdout, "--auto 静默同步成功")

    cross_case = fresh("cross")
    result = run_cli(cross_case, "--mode", "C", "--yes", "--source", "3", "--target", "2")
    check(
        result.returncode != 0 and "不属于同一世界" in (result.stdout + result.stderr),
        "跨世界 UUID 组操作被拒绝",
    )
    backups = mover.list_backups(cfgmod.load())
    if backups:
        result = run_cli(case, "--rollback", backups[0].name)
        check(result.returncode == 0 and "已回滚" in result.stdout, "--rollback 成功")


def test_simple() -> None:
    print("\n[7] 简易一键流程")
    case = fresh("one-click")
    config_file = ROOT / "config.json"
    cfgmod.save(
        {
            **cfgmod.DEFAULTS,
            "journeymapDir": str(case),
            "backupDir": str(ROOT / "tmp" / "backups" / "one-click"),
        }
    )
    result = run_cli(case, "--one-click", "--yes")
    check(
        result.returncode == 0 and "完成" in result.stdout,
        "--one-click 一键同步成功",
    )
    check("新增 42 个标点" in result.stdout, "输出说明新增数量")
    group = main_routes(case)
    check(
        all(len(list(route.waypoints_dir.glob("*.json"))) == 21 for route in group),
        "一键同步后三条线路各 21 个标点",
    )
    again = run_cli(case, "--one-click", "--yes")
    check(
        again.returncode == 0 and "无需改动" in again.stdout,
        "重复执行幂等并提示无需改动",
    )
    undone = run_cli(case, "--undo", "--yes")
    check(
        undone.returncode == 0 and "已撤销" in undone.stdout,
        "--undo 一键撤销成功",
    )
    after = [
        len(list(route.waypoints_dir.glob("*.json"))) for route in main_routes(case)
    ]
    check(after == [0, 0, 21], "撤销后恢复到 0 / 0 / 21")

    interaction = run_cli(case, stdin_text="\n\n0\n\n")
    check(
        "直接按回车 = 一键同步" in interaction.stdout,
        "简易主界面默认提示一键同步",
    )
    check("完成！" in interaction.stdout, "主界面按回车即可完成同步")
    check("已经一致，无需改动" in interaction.stdout, "同步后主界面显示已一致")

    advanced = run_cli(case, "--advanced")
    check(
        advanced.returncode == 0 and "已进入高级选项" in advanced.stdout,
        "--advanced 可进入高级菜单",
    )
    config_file.unlink(missing_ok=True)


def test_dist() -> None:
    print("\n[8] 发布包离线组装")
    result = subprocess.run(
        [PY, "tools/build_dist.py", "--offline", "--no-archive"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    package = ROOT / "dist" / "JourneyMapPointMove"
    check(
        result.returncode == 0
        and (package / "app" / "main.py").is_file()
        and (package / "LICENSE").is_file(),
        "离线组装发布目录（含 LICENSE）",
    )
    result = subprocess.run(
        [PY, "tools/build_dist.py", "--offline", "--format", "zip"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    check(
        result.returncode == 0
        and (ROOT / "dist" / "JourneyMapPointMove.zip").is_file(),
        "生成 zip 格式发布压缩包",
    )


def cleanup() -> None:
    for path in (ROOT / "backup", ROOT / "shared", ROOT / "dist", ROOT / "tmp"):
        if path.name == "tmp":
            if path.exists():
                for child in path.iterdir():
                    if child.is_dir():
                        remove_tree(child)
                    else:
                        child.unlink()
        else:
            if path.exists():
                remove_tree(path)
    config_file = ROOT / "config.json"
    if config_file.exists():
        config_file.unlink()


def main() -> int:
    global FIXTURE
    print("JourneyMapPointMove 自测开始（全部在 tmp/ 夹具上运行）")
    FIXTURE = build_fixture()
    try:
        test_paths()
        test_scan()
        test_c_mode_and_rollback()
        test_conflicts()
        test_junction()
        test_cli()
        test_simple()
        test_dist()
    finally:
        cleanup()
    print(f"\n自测结束：{'全部通过' if not FAILS else str(len(FAILS)) + ' 项失败'}")
    for message in FAILS:
        print(f"  - {message}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
