#!/usr/bin/env python3
"""Manage board knowledge boundaries and the external NEEQ retirement archive.

The live product has one active board, ChiNext. Base-layer and innovation-layer
assets are archived as an inspectable folder, not compressed into an opaque
package. Canonical JSON and binary assets are copied and hash-checked before
the exact retired source paths are removed from the live workspace.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import paths as workspace_paths
# 板块知识库（data/、templates/）位于知识根；归档与恢复都以知识根为范围。
KNOWLEDGE = workspace_paths.knowledge_of(ROOT)
ACTIVE_BOARD = "chinext"
RETIRED_BOARDS = ("base", "innovation")
BOARD_NAMES = {
    "base": "新三板基础层",
    "innovation": "新三板创新层",
    "chinext": "深交所创业板",
}

# These are the canonical board stores and the old root-level NEEQ store. The
# latter is retained in the archive because it is a historical source snapshot,
# not an active runtime store.
NEEQ_ARCHIVE_PATHS = (
    "data/public/boards/base",
    "data/public/boards/innovation",
    "templates/boards/base",
    "templates/boards/innovation",
    "data/modules",
    "data/public/catalog.json",
    "data/public/catalog-v0.2.1.json",
    "data/public/coverage.json",
    "data/public/acquisition.json",
    "data/public/formats.json",
    "data/public/instruments.json",
    "data/public/profiles.json",
    "data/public/rules.json",
    "data/public/disclosure_library.sqlite3",
    "data/public/layout_observations.json",
    "data/public/profiles",
    "data/scenarios/scenarios.json",
    "templates/manifest.json",
    "templates/manifest-v0.2.1.json",
    "templates/layout_profiles.json",
    "templates/board_resolution.docx",
    "templates/shareholder_notice.docx",
    "templates/management_change.docx",
    "templates/related_transaction.docx",
    "templates/litigation_arbitration.docx",
)
ASSET_ROOTS = ("data/public/", "templates/")
COMPANION_DIRS = {
    "data/public/originals",
    "data/public/documents",
    "data/public/extracted",
}
DEFAULT_ARCHIVE_PARENT = Path.home() / "NERO_Disclosure_Knowledge_Archive"


def read_json(path, default=None):
    path = Path(path)
    if not path.is_file():
        return default
    return json.loads(path.read_text("utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def iter_files(path):
    path = Path(path)
    if path.is_symlink():
        raise RuntimeError(f"归档源包含不允许的路径别名：{path}")
    if path.is_file():
        yield path
        return
    if path.is_dir():
        for child in sorted(path.rglob("*")):
            if child.is_symlink():
                raise RuntimeError(f"归档源包含不允许的路径别名：{child}")
            if child.is_file():
                yield child


def relative(root, path):
    return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()


def _json_values(value, key=""):
    if isinstance(value, dict):
        for name, child in value.items():
            yield from _json_values(child, name)
    elif isinstance(value, list):
        for child in value:
            yield from _json_values(child, key)
    elif isinstance(value, str):
        yield key, value


def _candidate_paths(root, current_file, key, value):
    """Resolve only declared path/file fields inside this workspace."""
    if "path" not in key.lower() and key != "file":
        return
    raw = Path(value)
    candidates = [raw] if raw.is_absolute() else [Path(root) / raw]
    if not raw.is_absolute() and key == "file":
        candidates.extend((Path(root) / "templates" / raw, Path(current_file).parent / raw))
    seen = set()
    root = Path(root).resolve()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            rel = resolved.relative_to(root).as_posix()
        except (OSError, ValueError):
            continue
        if rel in seen or not resolved.is_file():
            continue
        seen.add(rel)
        yield rel


def referenced_files(root, json_files):
    root = Path(root).resolve()
    found = set()
    for current in json_files:
        current = Path(current)
        try:
            data = read_json(current)
        except (OSError, ValueError, TypeError):
            continue
        for key, value in _json_values(data):
            found.update(_candidate_paths(root, current, key, value))
    return found


def _companion_files(root, rel):
    path = Path(rel)
    if path.parent.as_posix() not in COMPANION_DIRS:
        return set()
    source = Path(root) / path
    return {
        relative(root, sibling)
        for sibling in sorted(source.parent.glob(source.stem + ".*"))
        if sibling.is_file() and not sibling.is_symlink()
    }


def active_references(root):
    root = Path(root)
    json_files = []
    for board_path in (
        root / "data/public/boards/chinext",
        root / "templates/boards/chinext",
    ):
        if board_path.is_dir():
            json_files.extend(board_path.rglob("*.json"))
    return referenced_files(root, json_files)


def archive_plan(root=KNOWLEDGE):
    root = Path(root).resolve()
    explicit = {}
    missing = []
    for raw in NEEQ_ARCHIVE_PATHS:
        source = root / raw
        if not source.exists():
            missing.append(raw)
            continue
        for path in iter_files(source):
            rel = relative(root, path)
            explicit[rel] = "canonical_neeq_store"

    json_files = [root / rel for rel in explicit if rel.endswith(".json")]
    dependencies = referenced_files(root, json_files)
    for rel in tuple(dependencies):
        dependencies.update(_companion_files(root, rel))

    active = active_references(root)
    entries = {}
    for rel, category in explicit.items():
        entries[rel] = {
            "path": rel,
            "archive_path": rel,
            "category": category,
            "action": "move",
        }
    for rel in sorted(dependencies - explicit.keys()):
        if not any(rel.startswith(prefix) for prefix in ASSET_ROOTS):
            continue
        entries[rel] = {
            "path": rel,
            "archive_path": rel,
            "category": "neeq_dependency",
            "action": "copy_shared" if rel in active else "move",
        }

    return {
        "root": root,
        "missing_specs": missing,
        "active_references": active,
        "entries": [entries[key] for key in sorted(entries)],
    }


def _default_destination():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_ARCHIVE_PARENT / f"neeq-base-innovation-{stamp}"


def _assert_external(root, destination):
    root = Path(root).resolve()
    destination = Path(destination).expanduser().resolve()
    if destination == root or destination.is_relative_to(root):
        raise RuntimeError("外部归档目录必须位于当前工作区之外")
    if destination.exists():
        raise RuntimeError(f"归档目标已存在，为防止覆盖未继续：{destination}")
    return destination


def _archive_readme(destination, report):
    return """# NERO Disclosure 新三板知识库外部归档

本目录是从 `{source_root}` 迁出的基础层和创新层知识资产归档，生成时间为 `{created_at}`。

- 当前工作区运行范围：仅深交所创业板（`chinext`）。
- 归档对象：基础层/创新层独立 catalog、SQLite 检索投影、法规/案例/文种配置、旧版根目录知识库快照、相关模板及其 NEEQ 专属原件/正文依赖。
- 存储形式：保持原工作区相对路径的普通文件夹；不压缩、不迁移凭据和 `var/` 事项记录。
- 完整性：`archive-manifest.json` 记录每个文件的来源相对路径、动作、字节数和 SHA-256。
- 共享依赖：与创业板仍共用的文件只复制到本归档，不从工作区删除；其余列为 `move` 的文件已在哈希核对后移出。
- 回滚：仅在明确需要恢复新三板资料时，使用工作区脚本的 `restore-neeq --source <本目录> --yes`；恢复资料不会自动重新开放板块，重新启用需另行审查并修改唯一板块控制点。

本归档只保留资料和历史配置，不代表法规适用性、案例完整性、格式合规性或人工专业验收已经完成。
""".format(source_root=report["source_root"], created_at=report["created_at"])


def archive_neeq(root=KNOWLEDGE, destination=None, *, confirm=False, dry_run=False):
    root = Path(root).resolve()
    destination = _assert_external(root, destination or _default_destination())
    plan = archive_plan(root)
    if not plan["entries"]:
        raise RuntimeError("未找到基础层/创新层知识资产，未创建归档")
    if not confirm and not dry_run:
        raise RuntimeError("归档会移出明确列出的新三板资产；请使用 --yes 确认")

    moved = sum(item["action"] == "move" for item in plan["entries"])
    shared = sum(item["action"] == "copy_shared" for item in plan["entries"])
    report = {
        "schema_version": "nero.disclosure.neeq_archive.v1",
        "status": "planned" if dry_run else "staged",
        "source_root": str(root),
        "archive_dir": str(destination),
        "active_board": ACTIVE_BOARD,
        "retired_boards": list(RETIRED_BOARDS),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "missing_specs": plan["missing_specs"],
        "file_count": len(plan["entries"]),
        "moved_file_count": moved,
        "copied_shared_file_count": shared,
        "files": [],
    }
    if dry_run:
        report["files"] = plan["entries"]
        return report

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.staging-{os.getpid()}"
    if staging.exists():
        raise RuntimeError(f"发现未清理的临时归档目录，未覆盖：{staging}")
    staging.mkdir(parents=True)
    renamed = False
    try:
        for item in plan["entries"]:
            source = root / item["path"]
            if not source.is_file():
                raise RuntimeError(f"归档源在复制前发生变化：{item['path']}")
            digest = sha256_file(source)
            target = staging / item["archive_path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied_digest = sha256_file(target)
            if copied_digest != digest:
                raise RuntimeError(f"归档副本哈希不符：{item['path']}")
            report["files"].append({**item, "bytes": source.stat().st_size, "sha256": digest})

        write_json(staging / "archive-manifest.json", report)
        (staging / "README.md").write_text(_archive_readme(destination, report), encoding="utf-8")
        if len(report["files"]) != report["file_count"]:
            raise RuntimeError("归档文件数在复制过程中发生变化")

        staging.rename(destination)
        renamed = True

        for item in report["files"]:
            if item["action"] != "move":
                continue
            source = root / item["path"]
            if source.is_file():
                source.unlink()

        # Remove only the explicitly listed retired directories after their
        # files have been copied. Shared raw assets are never removed here.
        for raw in NEEQ_ARCHIVE_PATHS:
            source = root / raw
            if source.is_dir() and source.exists():
                shutil.rmtree(source)

        missing_active = [rel for rel in sorted(plan["active_references"]) if not (root / rel).is_file()]
        if missing_active:
            raise RuntimeError("创业板依赖被意外移出：" + ", ".join(missing_active))

        report.update(
            status="completed",
            completed_at=datetime.now(timezone.utc).isoformat(),
            active_dependencies_retained=len(plan["active_references"]),
        )
        write_json(destination / "archive-manifest.json", report)
        write_json(destination / "retirement-receipt.json", report)
        return report
    except Exception:
        if not renamed and staging.exists():
            shutil.rmtree(staging)
        raise


def _board_stats(root, board):
    public = Path(root) / "data/public/boards" / board
    if not public.is_dir():
        return {"status": "archived", "board": board}
    catalog = read_json(public / "catalog.json", {}) or {}
    return {
        "status": "active_data_present",
        "board": board,
        "sources": len(catalog.get("sources", [])),
        "cases": len(catalog.get("cases", [])),
        "blacklist_cases": len(catalog.get("blacklist_cases", [])),
        "profiles": len(read_json(public / "profiles.json", []) or []),
        "instruments": len(read_json(public / "instruments.json", []) or []),
        "rules": len(read_json(public / "rules.json", []) or []),
        "scenarios": len(read_json(public / "scenarios.json", []) or []),
        "sqlite_bytes": (public / "disclosure_library.sqlite3").stat().st_size
        if (public / "disclosure_library.sqlite3").is_file()
        else 0,
    }


def cmd_list(_args):
    print("=== NERO_Disclosure 板块知识库状态 ===")
    for board in (*RETIRED_BOARDS, ACTIVE_BOARD):
        value = _board_stats(KNOWLEDGE, board)
        if value["status"] == "archived":
            print(f"[{board.upper()}] {BOARD_NAMES[board]}：已从当前工作区归档")
            continue
        print(
            f"[{board.upper()}] {BOARD_NAMES[board]}："
            f"法规/条文 {value['sources']}，案例 {value['cases']}，"
            f"黑名单 {value['blacklist_cases']}，Profile {value['profiles']}，"
            f"制度 {value['instruments']}，规则 {value['rules']}，模拟 {value['scenarios']}"
        )
    print(f"当前开发范围：{ACTIVE_BOARD}（仅创业板）")
    print("========================================")


def cmd_archive(args):
    destination = args.destination or _default_destination()
    report = archive_neeq(KNOWLEDGE, destination, confirm=args.yes, dry_run=args.dry_run)
    print(json.dumps({k: v for k, v in report.items() if k != "files"}, ensure_ascii=False, indent=2))
    if args.dry_run:
        print("dry-run：未创建归档、未移出任何工作区文件。")
        return 0
    print(f"新三板知识库已归档到外部目录：{report['archive_dir']}")
    print("当前工作区保留创业板及其共享原件依赖；请重新启动 WebUI 后读取新的板块边界。")
    return 0


def _find_archive(source=None):
    if source:
        candidate = Path(source).expanduser().resolve()
        if (candidate / "archive-manifest.json").is_file():
            return candidate
        raise RuntimeError(f"未找到归档清单：{candidate / 'archive-manifest.json'}")
    candidates = sorted(DEFAULT_ARCHIVE_PARENT.glob("neeq-base-innovation-*/archive-manifest.json"))
    if not candidates:
        raise RuntimeError("未找到外部新三板归档，请使用 --source 指定归档目录")
    return candidates[-1].parent


def cmd_restore(args):
    if not args.yes:
        raise RuntimeError("恢复会把归档资料复制回工作区；请使用 --yes 确认")
    archive = _find_archive(args.source)
    manifest = read_json(archive / "archive-manifest.json")
    root = KNOWLEDGE.resolve()
    restored = 0
    for item in manifest.get("files", []):
        target = (root / item["path"]).resolve()
        if not target.is_relative_to(root):
            raise RuntimeError(f"归档路径越界：{item['path']}")
        source = archive / item["archive_path"]
        if not source.is_file() or sha256_file(source) != item["sha256"]:
            raise RuntimeError(f"归档文件哈希不符：{item['archive_path']}")
        if target.exists():
            if target.is_file() and sha256_file(target) == item["sha256"]:
                continue
            raise RuntimeError(f"恢复目标已存在且内容不同：{target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        restored += 1
    print(json.dumps({"status": "restored_data_only", "archive": str(archive), "restored_files": restored,
                      "active_board": ACTIVE_BOARD,
                      "note": "恢复资料不会自动重新开放基础层或创新层"}, ensure_ascii=False, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description="NERO_Disclosure 板块知识库管理")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("list", help="查看当前板块知识库状态")

    archive_parser = subparsers.add_parser(
        "archive-neeq", help="将基础层和创新层知识库归档到工作区外，并切换为创业板-only数据面"
    )
    archive_parser.add_argument("--destination", type=Path, help="外部归档目录；默认在用户目录下创建普通文件夹")
    archive_parser.add_argument("-y", "--yes", action="store_true", help="确认移出已列明的基础层/创新层资产")
    archive_parser.add_argument("--dry-run", action="store_true", help="只输出归档计划，不创建或移出文件")

    remove_parser = subparsers.add_parser("remove-neeq", help="archive-neeq 的兼容别名")
    remove_parser.add_argument("--destination", type=Path)
    remove_parser.add_argument("-y", "--yes", action="store_true")
    remove_parser.add_argument("--dry-run", action="store_true")

    restore_parser = subparsers.add_parser("restore-neeq", help="从外部归档复制回新三板资料；不自动重新开放板块")
    restore_parser.add_argument("--source", type=Path, help="外部归档目录")
    restore_parser.add_argument("-y", "--yes", action="store_true", help="确认复制资料回当前工作区")

    args = parser.parse_args()
    if args.command == "list" or args.command is None:
        cmd_list(args)
        return 0
    if args.command in ("archive-neeq", "remove-neeq"):
        return cmd_archive(args)
    if args.command == "restore-neeq":
        return cmd_restore(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"未完成：{exc}", file=sys.stderr)
        raise SystemExit(2)
