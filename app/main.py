"""控制台入口与交互流程。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import VERSION
from app import config as cfgmod
from app import mover
from app import scanner
from app.models import Route


def setup_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass


def ask(prompt: str, default: str = "", auto_yes: bool = False) -> str:
    if auto_yes:
        return default
    try:
        value = input(prompt)
    except EOFError:
        return default
    return value if value.strip() else default


def confirm(prompt: str, auto_yes: bool) -> bool:
    if auto_yes:
        return True
    return ask(prompt, "y").strip().lower() in ("y", "yes", "")


def short_uuid(key: str) -> str:
    if key.startswith("UNKNOWN:"):
        return "未识别"
    return key.split("-")[0][:8]


def print_routes(routes: list[Route]) -> None:
    print("\n线路清单：")
    print(f"{'编号':<4}{'空间':<4}{'世界':<10}{'标点':<6}{'维度':<10}{'链接':<4}目录名")
    for index, route in enumerate(routes, 1):
        dims = ",".join(str(value) for value in sorted(route.dimension_set)) or "-"
        link = "是" if route.is_junction else "否"
        print(
            f"{index:<4}{route.space:<4}{short_uuid(route.group_key):<10}"
            f"{len(route.waypoints):<6}{dims:<10}{link:<4}{route.name}"
        )
    if not routes:
        print("（未发现线路目录）")


def print_groups(routes: list[Route]) -> list[list[Route]]:
    groups = scanner.group(routes)
    print("\n世界分组：")
    values: list[list[Route]] = []
    for index, (key, items) in enumerate(groups.items(), 1):
        total = sum(len(route.waypoints) for route in items)
        suffix = "  （身份未知，不参与自动合并）" if key.startswith("UNKNOWN:") else ""
        print(f"  G{index}  {short_uuid(key)}  线路 {len(items)} 条  标点 {total} 个{suffix}")
        values.append(items)
    return values


def parse_indices(text: str, routes: list[Route]) -> list[Route]:
    result: list[Route] = []
    for part in text.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit() or not (1 <= int(part) <= len(routes)):
            raise ValueError(f"无效编号：{part}")
        result.append(routes[int(part) - 1])
    return result


def default_group(routes: list[Route]) -> list[Route]:
    """返回标点总数最多的已识别世界分组。"""
    best: tuple[int, list[Route]] | None = None
    for key, items in scanner.group(routes).items():
        if key.startswith("UNKNOWN:"):
            continue
        total = sum(len(route.waypoints) for route in items)
        if best is None or total > best[0]:
            best = (total, items)
    return best[1] if best and best[0] > 0 else []


def save_dir(cfg: dict, path: Path, kind: str, raw: str = "") -> None:
    """把识别结果写入配置，后续启动无需再输入。"""
    cfg["journeymapDir"] = str(path)
    cfg["inputType"] = kind
    cfg["gameDir"] = raw if kind == "gameDir" else ""
    cfgmod.save(cfg)
    print(f"已记住这个目录，以后打开不用再输：{path}")


def resolve_dir(cfg: dict, args: argparse.Namespace):
    """读取已保存的目录；首次使用时引导玩家选择目录。"""
    if args.jm_dir:
        path, _kind = cfgmod.resolve(args.jm_dir)
        if not path:
            raise SystemExit(f"无法识别目录：{args.jm_dir}")
        print(f"本次使用目录：{path}")
        return path

    stored = cfg.get("journeymapDir", "")
    if stored and cfgmod.validate_journeymap(Path(stored)):
        print(f"游戏目录：{stored}")
        print("（要换目录，在主界面选 [2]）")
        return Path(stored)
    return first_time(cfg, args)


def first_time(cfg: dict, args: argparse.Namespace):
    """首次配置：先自动搜索常见位置，找不到再请玩家拖入目录。"""
    print("\n第一次使用，先告诉工具游戏装在哪。")
    print("最简单：把游戏目录或 journeymap 文件夹直接拖进这个窗口，再按回车。")
    print("不知道在哪也没关系，直接按回车让我自动找。")
    while True:
        raw = ask("\n路径（回车=自动搜索，输入 0 退出）: ", "", args.yes)
        if raw.strip() == "0":
            raise SystemExit("已退出。")
        if not raw.strip():
            if args.yes:
                raise SystemExit(
                    "自动模式下没有已保存的目录：请先手动运行一次，或用 --jm-dir 指定。"
                )
            print("正在搜索常见的游戏位置，稍等几秒……")
            candidates = cfgmod.rank_candidates(cfgmod.discover())
            if not candidates:
                print("没找到。请把游戏目录拖进窗口，或者输入它的完整路径。")
                continue
            print("\n找到了这些位置（按最近使用排序，第 1 个最可能是你要的）：")
            for index, path in enumerate(candidates, 1):
                note = (
                    f"  （{cfgmod.waypoint_count(path)} 个标点，最近在用，推荐）"
                    if index == 1
                    else ""
                )
                print(f"  [{index}] {path}{note}")
            if len(candidates) == 1:
                path, kind = candidates[0], "journeymapDir"
                print(f"找到并选用：{path}")
                print("（要换目录，在主界面选 [2]）")
            else:
                pick = ask(
                    "输入编号选用（回车=第 1 个），也可以直接拖入其它目录: ", "1"
                ).strip()
                if pick.isdigit() and 1 <= int(pick) <= len(candidates):
                    path, kind = candidates[int(pick) - 1], "journeymapDir"
                else:
                    path, kind = cfgmod.resolve(pick)
        else:
            path, kind = cfgmod.resolve(raw)
        if path:
            save_dir(cfg, path, kind, raw)
            return path
        if args.yes:
            raise SystemExit(f"无法识别目录：{raw}")
        print("没认出来：这个目录下应该能找到 journeymap/data/mp。")


def choose_conflict(args: argparse.Namespace, cfg: dict, auto_yes: bool) -> str:
    if args.conflict:
        return args.conflict
    default = cfg.get("defaultConflict", "skip")
    if auto_yes:
        return default
    label = mover.CONFLICT_LABELS.get(default, "跳过")
    number = {"skip": "1", "overwrite": "2", "keepBoth": "3"}.get(default, "1")
    raw = ask(f"冲突策略 [1 跳过 / 2 覆盖 / 3 两者都保留]（回车={label}）: ", number)
    return {"1": "skip", "2": "overwrite", "3": "keepBoth"}.get(raw.strip(), default)


def warn_game(auto_yes: bool) -> None:
    if auto_yes:
        return
    print("请先关闭游戏客户端，避免 JourneyMap 运行期写回覆盖结果。")
    if not confirm("已关闭？[Y/n] ", False):
        raise SystemExit("已取消，未执行写操作。")


def ensure_same_group(routes: list[Route], force: bool) -> None:
    keys = {route.group_key for route in routes}
    if len(keys) > 1 or any(key.startswith("UNKNOWN:") for key in keys):
        if not force:
            raise ValueError(
                "参与线路不属于同一世界 UUID 组；跨组坐标不通用，已拒绝。"
                "确需继续时请自行确认风险。"
            )


def update_cfg(
    cfg: dict, mode: str, sources: list[Route], targets: list[Route], conflict: str
) -> None:
    cfg["lastMode"] = mode
    cfg["lastSource"] = sources[0].name if sources else ""
    cfg["lastTargets"] = [route.name for route in targets]
    cfg["defaultConflict"] = conflict
    cfg["lastSyncAt"] = datetime.now().isoformat(timespec="seconds")
    cfgmod.save(cfg)


def perform(
    cfg: dict,
    routes: list[Route],
    mode: str,
    sources: list[Route],
    targets: list[Route],
    conflict: str,
    auto_yes: bool,
    force: bool = False,
) -> int:
    if not sources or not targets:
        raise ValueError("必须指定源线路与目标线路")
    if mode in ("C", "D"):
        ensure_same_group(list({route.name: route for route in sources + targets}.values()), force)

    print(f"\n模式：{mode} {mover.MODE_LABELS[mode]}；冲突策略：{mover.CONFLICT_LABELS[conflict]}")
    print("源线路：" + "、".join(route.name for route in sources))
    print("目标线路：" + "、".join(route.name for route in targets))

    if mode == "D":
        print("将建立共享目录，各线路的 waypoints 改为目录联接。")
        if not confirm("确认执行？[Y/n] ", auto_yes):
            print("已取消。")
            return 0
        warn_game(auto_yes)
        snapshot = mover.backup(list({route.name: route for route in sources + targets}.values()), cfg, mode, "建立共享目录前")
        print(f"已备份：{snapshot}")
        shared = mover.setup_junction(targets)
        print(f"共享目录：{shared}")
        for route in targets:
            state = "有效" if route.waypoints_dir.is_junction() else "失败"
            print(f"  {route.name} -> {state}")
        update_cfg(cfg, mode, sources, targets, conflict)
        print("完成：各线路已共享同一份标点。请重新进入游戏查看。")
        return len(targets)

    plan = mover.build_plan(mode, sources, targets, conflict)
    print("\n变更预览：")
    print(
        f"  新增 {plan.count('copy')} 个，覆盖 {plan.count('overwrite')} 个，"
        f"另存 {plan.count('rename')} 个，跳过 {plan.count('skip')} 个"
    )
    print(f"  将写入 {plan.writable_count} 个文件")
    if plan.writable_count == 0:
        print("无需写入。")
        return 0
    if not confirm("确认执行？[Y/n] ", auto_yes):
        print("已取消。")
        return 0
    warn_game(auto_yes)
    snapshot = mover.backup(targets, cfg, mode, f"{mode}/{conflict}")
    print(f"已备份：{snapshot}")
    written = mover.execute(plan)
    update_cfg(cfg, mode, sources, targets, conflict)
    print(f"完成：写入 {written} 个文件。请重新进入游戏查看标点。")
    return written


def run_auto(cfg: dict, routes: list[Route], args: argparse.Namespace) -> int:
    picked = default_group(routes)
    if not picked:
        print("未找到含标点的同一世界 UUID 分组，无法自动同步。")
        return -1
    mode = args.mode or "C"
    conflict = args.conflict or cfg.get("defaultConflict", "skip")
    return perform(cfg, routes, mode, picked, picked, conflict, True, args.force)


def run_mode(cfg: dict, routes: list[Route], args: argparse.Namespace) -> int:
    conflict = choose_conflict(args, cfg, args.yes)
    sources = parse_indices(args.source, routes) if args.source else []
    targets = parse_indices(args.target, routes) if args.target else []
    if args.mode in ("C", "D"):
        if not sources and not targets:
            sources = targets = default_group(routes)
            if not sources:
                raise SystemExit("未找到含标点的同一世界 UUID 分组。")
        elif not sources:
            sources = list(targets)
        elif not targets:
            targets = list(sources)
    if not sources or not targets:
        raise SystemExit("A/B 模式需要 --source 与 --target 指定线路编号。")
    return perform(cfg, routes, args.mode, sources, targets, conflict, args.yes, args.force)


def group_summary(routes: list[Route]) -> str:
    """把扫描结果翻译成玩家能直接看懂的几句话，不出现内部术语。"""
    picked = default_group(routes)
    if not picked:
        return (
            f"共找到 {len(routes)} 条线路，但没找到属于同一个世界的多条线路，\n"
            "暂时不需要同步（也可能这些线路还没有任何标点）。"
        )
    total = len({waypoint.key for route in picked for waypoint in route.waypoints})
    counts = [len(route.waypoints) for route in picked]
    with_points = sum(1 for count in counts if count)
    keysets = [{waypoint.key for waypoint in route.waypoints} for route in picked]
    consistent = all(keys == keysets[0] for keys in keysets)
    lines = [
        f"共找到 {len(routes)} 条线路，其中 {len(picked)} 条属于同一个世界。",
        f"这个世界的标点一共 {total} 个。",
    ]
    if consistent:
        lines.append(
            f"{len(picked)} 条线路现在都有这 {total} 个标点，已经一致，无需改动。"
        )
    else:
        lines.append(
            f"目前只有 {with_points} 条线路有标点，另外 "
            f"{len(picked) - with_points} 条是空的 —— "
            "切换线路看不到标点就是这个原因。"
        )
    return "\n".join(lines)


def one_click_sync(cfg: dict, routes: list[Route]) -> int:
    """一键同步：同世界各线路补齐标点，不覆盖已有标点，执行前自动备份。

    主界面唯一默认动作，不要求玩家二次确认；安全网是自动备份与一键撤销。
    """
    picked = default_group(routes)
    if not picked:
        print("没有找到可以同步的线路，未改动任何文件。")
        return 0
    plan = mover.build_plan("C", picked, picked, "skip")
    if plan.writable_count == 0:
        print("所有线路已经一致，无需改动。")
        return 0
    total = len({waypoint.key for route in picked for waypoint in route.waypoints})
    print(f"\n把 {total} 个标点补齐到 {len(picked)} 条线路：")
    print(f"  新增 {plan.count('copy')} 个标点，已有的标点保持不变。")
    print("  提示：最好先关掉游戏客户端，避免游戏把结果覆盖回去。")
    print("  正在自动备份并同步……")
    snapshot = mover.backup(picked, cfg, "C", "一键同步前")
    print(f"  备份：{snapshot.name}")
    written = mover.execute(plan)
    update_cfg(cfg, "C", picked, picked, "skip")
    counts = [len(list(route.waypoints_dir.glob("*.json"))) for route in picked]
    print(f"\n完成！{len(picked)} 条线路现在各有 {max(counts)} 个标点。")
    print("重新进入游戏就能看到了。")
    print("想撤销的话，回到主界面选 [1]。")
    return written


def undo_last(cfg: dict) -> int:
    """撤销最近一次同步，玩家不需要理解备份时间戳。"""
    backups = mover.list_backups(cfg)
    if not backups:
        print("还没有备份，没有可以撤销的操作。")
        return 0
    latest = backups[0]
    count = mover.rollback(latest.name, cfg)
    print(f"已撤销最近一次同步（{latest.name}），还原了 {count} 个文件。")
    return count


def simple_loop(
    cfg: dict, routes: list[Route], args: argparse.Namespace, journeymap_dir: Path
) -> int:
    """简易主界面：默认动作就是直接按回车完成同步。"""
    if args.yes:
        outcome = one_click_sync(cfg, routes)
        return 0 if outcome >= 0 else 1
    current = journeymap_dir
    while True:
        print("\n" + "=" * 56)
        print(f"  旅行地图标点搬运   v{VERSION}")
        print("=" * 56)
        summary = group_summary(routes)
        print(f"正在检查：{current}")
        print(summary)
        print("-" * 56)
        if "无需改动" in summary:
            print("  已经同步好了，不用再操作。")
            print("  直接按回车 = 再检查一次")
        else:
            print("  直接按回车 = 一键同步（推荐）")
            print("  把标点补齐到这个世界的每条线路，不覆盖已有标点。")
        print("-" * 56)
        print("  [1] 撤销上一次同步    [2] 更换游戏目录")
        print("  [3] 高级选项          [0] 退出")
        choice = ask("\n请选择（回车 = 一键同步）: ", "").strip()
        if choice == "0":
            return 0
        if choice == "":
            one_click_sync(cfg, routes)
        elif choice == "1":
            undo_last(cfg)
        elif choice == "2":
            cfg["journeymapDir"] = ""
            cfgmod.save(cfg)
            current = first_time(cfg, args)
        elif choice == "3":
            signal = advanced_loop(cfg, routes, args)
            if signal == -1:
                cfg["journeymapDir"] = ""
                cfgmod.save(cfg)
                current = first_time(cfg, args)
        else:
            print("没看懂这个选项；直接按回车就是一键同步。")
            ask("\n按回车返回主界面...", "", args.yes)
            continue
        routes = scanner.scan(current)
        ask("\n按回车返回主界面...", "", args.yes)


def advanced_loop(cfg: dict, routes: list[Route], args: argparse.Namespace) -> int:
    """高级菜单：保留全部手动能力，普通玩家无需进入。"""
    print("\n已进入高级选项。普通使用请按 [0] 返回，直接按回车一键同步即可。")
    while True:
        print_routes(routes)
        groups = print_groups(routes)
        print("\n[1] A 单线搬运   [2] B 合并到主线路   [3] C 全线路同步")
        print("[4] D 实时共享   [5] 检测并修复共享链接   [6] 导出备份 zip")
        print("[7] 从备份回滚   [8] 清空目录配置   [0] 返回简易主界面")
        choice = ask("请选择: ", "0").strip()
        try:
            if choice == "0":
                return 0
            if choice in ("1", "2", "3", "4"):
                mode = {"1": "A", "2": "B", "3": "C", "4": "D"}[choice]
                conflict = choose_conflict(args, cfg, False)
                if mode in ("C", "D"):
                    if not groups:
                        continue
                    raw = ask("选择世界分组编号（回车=第 1 组）: ", "1").strip()
                    index = int(raw) if raw.isdigit() else 1
                    if not (1 <= index <= len(groups)):
                        print("分组编号无效。")
                        continue
                    picked = [
                        route
                        for route in groups[index - 1]
                        if not route.group_key.startswith("UNKNOWN:")
                    ]
                    sources = targets = picked
                else:
                    sources = parse_indices(ask("源线路编号（多个用逗号分隔）: "), routes)
                    targets = parse_indices(ask("目标线路编号（多个用逗号分隔）: "), routes)
                perform(cfg, routes, mode, sources, targets, conflict, False)
            elif choice == "5":
                if not groups:
                    continue
                raw = ask("选择世界分组编号（回车=第 1 组）: ", "1").strip()
                index = int(raw) if raw.isdigit() else 1
                picked = groups[index - 1]
                states = mover.check_junctions(picked)
                for route, valid in states:
                    print(f"  {'有效' if valid else '需修复'}  {route.name}")
                broken = [route for route, valid in states if not valid]
                if broken and confirm("修复失效链接？[Y/n] ", False):
                    count = mover.repair_junctions(broken)
                    print(f"已修复 {count} 条线路。")
            elif choice == "6":
                output = mover.export_backup_zip(cfg)
                print(f"已导出：{output}" if output else "尚无备份可导出。")
            elif choice == "7":
                backups = mover.list_backups(cfg)
                if not backups:
                    print("尚无备份。")
                    continue
                for index, path in enumerate(backups, 1):
                    print(f"  {index}  {path.name}")
                raw = ask("选择备份编号（回车=最新）: ", "1").strip()
                index = int(raw) if raw.isdigit() else 1
                if not (1 <= index <= len(backups)):
                    print("备份编号无效。")
                    continue
                if confirm(f"确认回滚到 {backups[index - 1].name}？[Y/n] ", False):
                    count = mover.rollback(backups[index - 1].name, cfg)
                    print(f"已回滚 {count} 个文件。")
            elif choice == "8":
                return -1
            else:
                print("无效选择。")
        except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
            print(f"操作未完成：{exc}")
        ask("\n按回车返回高级菜单...", "", args.yes)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JourneyMap 多线路标点搬运工具")
    parser.add_argument("--auto", action="store_true", help="用默认分组静默执行全线路同步")
    parser.add_argument("--jm-dir", help="本次运行使用的 journeymap 目录，不写入配置")
    parser.add_argument("--yes", action="store_true", help="跳过所有确认提示")
    parser.add_argument("--mode", choices=["A", "B", "C", "D"], help="直接执行指定模式")
    parser.add_argument("--conflict", choices=["skip", "overwrite", "keepBoth"])
    parser.add_argument("--source", help="源线路编号，逗号分隔")
    parser.add_argument("--target", help="目标线路编号，逗号分隔")
    parser.add_argument("--force", action="store_true", help="允许跨世界 UUID 组操作")
    parser.add_argument("--list", action="store_true", help="只列出线路后退出")
    parser.add_argument("--rollback", help="回滚到指定备份时间戳")
    parser.add_argument("--repair", action="store_true", help="修复共享链接")
    parser.add_argument("--one-click", action="store_true", help="一键同步后退出")
    parser.add_argument("--undo", action="store_true", help="撤销最近一次同步后退出")
    parser.add_argument("--advanced", action="store_true", help="直接进入高级菜单")
    parser.add_argument("--discover", action="store_true", help="列出自动搜索到的游戏目录")
    return parser


def main() -> int:
    setup_stdout()
    args = build_parser().parse_args()
    cfg = cfgmod.load()

    if args.discover:
        found = cfgmod.rank_candidates(cfgmod.discover())
        if not found:
            print("没有自动找到 journeymap 目录，请手动指定路径。")
        for path in found:
            print(path)
        return 0

    if args.rollback:
        try:
            count = mover.rollback(args.rollback, cfg)
            print(f"已回滚 {count} 个文件。")
            return 0
        except (OSError, RuntimeError, KeyError, json.JSONDecodeError) as exc:
            print(f"回滚失败：{exc}")
            return 1

    if args.undo:
        try:
            undo_last(cfg)
            return 0
        except (OSError, RuntimeError, KeyError, json.JSONDecodeError) as exc:
            print(f"撤销失败：{exc}")
            return 1

    journeymap_dir = resolve_dir(cfg, args)
    routes = scanner.scan(journeymap_dir)

    if args.list:
        print_routes(routes)
        print_groups(routes)
        return 0

    if args.repair:
        picked = (
            parse_indices(args.source, routes) if args.source else default_group(routes)
        )
        broken = [route for route, valid in mover.check_junctions(picked) if not valid]
        print(f"发现 {len(broken)} 条失效链接。")
        count = mover.repair_junctions(broken)
        print(f"已修复 {count} 条线路。")
        return 0

    try:
        if args.one_click:
            outcome = one_click_sync(cfg, routes)
            return 0 if outcome >= 0 else 1
        if args.auto:
            outcome = run_auto(cfg, routes, args)
            return 0 if outcome >= 0 else 1
        if args.mode:
            outcome = run_mode(cfg, routes, args)
            return 0 if outcome >= 0 else 1
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"操作未完成：{exc}")
        return 1

    if args.advanced:
        return advanced_loop(cfg, routes, args)

    result = simple_loop(cfg, routes, args, journeymap_dir)
    if not args.yes:
        ask("\n按回车退出...")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
