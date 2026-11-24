"""构建飞牛 fnOS 应用包（.fpk）。

fpk 结构（fnpack 产物布局）:
    manifest  LICENSE  ICON.PNG  ICON_256.PNG  *.sc
    config/{privilege,resource}
    cmd/{main,install_init,install_callback,upgrade_init,upgrade_callback,
         uninstall_init,uninstall_callback,config_init,config_callback}
    wizard/{install,upgrade,config,uninstall}
    app.tgz          <- app/ 目录打包，安装后解压为 $TRIM_APPDEST

执行: python fnos/build_fpk.py
"""
from __future__ import annotations

import gzip
import io
import json
import os
import re
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG = ROOT / "garage-keeper"
APP_DIR = PKG / "app"
DIST = ROOT.parent / "dist"

TEXT_SUFFIXES = {"", ".sh", ".sc", ".json", ".txt", ".md", ".html", ".css", ".js", ".py", ".svg"}
EXEC_FILES = {
    "cmd/main", "cmd/install_init", "cmd/install_callback", "cmd/upgrade_init",
    "cmd/upgrade_callback", "cmd/uninstall_init", "cmd/uninstall_callback",
    "cmd/config_init", "cmd/config_callback",
}
REQUIRED = [
    "manifest", "ICON.PNG", "ICON_256.PNG",
    "config/privilege", "config/resource",
    "wizard/install", "wizard/upgrade",
    *sorted(EXEC_FILES),
]
APP_REQUIRED = [
    "ui/index.html", "ui/app.js", "ui/styles.css", "ui/config",
    "ui/images/icon_64.png", "ui/images/icon_256.png",
    "server/garage.py", "server/api.py", "server/store.py",
    "server/calc.py", "server/nlp.py", "server/backup.py",
]
SKIP_DIRS = {"__pycache__", ".git", ".idea", "node_modules"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".db", ".db-wal", ".db-shm", ".log", ".pid"}

MANIFEST_VERSION = re.compile(r"^version\s*=\s*(\S+)$", re.MULTILINE)
PLATFORMS = {"x86", "arm", "all"}


def manifest_field(text: str, key: str, default: str = "") -> str:
    match = re.search(rf"^{key}\s*=\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else default


def log(msg: str) -> None:
    print(msg, flush=True)


def ensure_icons() -> None:
    """图标不入版本库（二进制），构建时用 make_icon.py 自动重建。"""
    targets = [
        PKG / "ICON.PNG",
        PKG / "ICON_256.PNG",
        PKG / "app" / "ui" / "images" / "icon_64.png",
        PKG / "app" / "ui" / "images" / "icon_256.png",
    ]
    missing = [p for p in targets if not p.exists()]
    if not missing:
        return
    try:
        import make_icon
    except ImportError as exc:  # 缺 Pillow 时给出明确指引
        raise SystemExit(
            "缺少图标且无法自动生成：%s\n请先安装 Pillow（pip install pillow）后重试。" % exc
        )
    log("[0/3] 图标缺失，调用 make_icon.py 重新生成")
    make_icon.main()
    still = [p for p in targets if not p.exists()]
    if still:
        raise SystemExit("图标生成失败：" + ", ".join(str(p) for p in still))


def validate() -> str:
    missing = [p for p in REQUIRED if not (PKG / p).exists()]
    if missing:
        raise SystemExit("缺少必需文件：\n  " + "\n  ".join(missing))

    manifest = (PKG / "manifest").read_text(encoding="utf-8")
    if "source" not in manifest or "thirdparty" not in manifest:
        raise SystemExit("manifest 缺少 source = thirdparty")

    for rel in ("config/privilege", "config/resource", "wizard/install", "wizard/upgrade",
                "wizard/config", "wizard/uninstall", "app/ui/config"):
        path = PKG / rel
        try:
            json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{rel} 不是合法 JSON：{exc}")

    version = MANIFEST_VERSION.search(manifest)
    if not version or not re.fullmatch(r"\d+\.\d+\.\d+", version.group(1)):
        raise SystemExit(f"manifest version 必须为 X.Y.Z 形式，当前：{version.group(1) if version else '缺失'}")

    appname = manifest_field(manifest, "appname")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", appname or ""):
        raise SystemExit(f"manifest appname 缺失或格式非法：{appname!r}")

    platform = manifest_field(manifest, "platform", "x86").lower()
    if platform not in PLATFORMS:
        raise SystemExit(f"manifest platform 只能取 x86 / arm / all，当前：{platform!r}")

    # platform=all 仅适用于不含原生二进制的纯脚本/静态资源应用
    if platform == "all":
        for path in (APP_DIR.rglob("*")):
            if path.is_file() and path.read_bytes()[:4] == b"\x7fELF":
                raise SystemExit(f"platform=all 的包内不应出现 ELF 二进制：{path.relative_to(APP_DIR)}")

    for rel in EXEC_FILES:
        text = (PKG / rel).read_bytes()
        if not text.startswith(b"#!"):
            raise SystemExit(f"{rel} 缺少 shebang")

    for icon, size in (("ICON.PNG", 64), ("ICON_256.PNG", 256)):
        if (PKG / icon).stat().st_size > 1024 * 1024:
            raise SystemExit(f"{icon} 超过 1MB")
        with open(PKG / icon, "rb") as fh:
            head = fh.read(24)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            raise SystemExit(f"{icon} 不是 PNG")
        width = int.from_bytes(head[16:20], "big")
        if width != size:
            raise SystemExit(f"{icon} 尺寸应为 {size}px，实际 {width}px")

    return {"version": version.group(1), "appname": appname, "platform": platform}


def normalize_text(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def iter_package_files(base: Path, prefix: str = ""):
    for entry in sorted(base.iterdir()):
        rel = f"{prefix}{entry.name}"
        if entry.is_dir():
            if entry.name in SKIP_DIRS:
                continue
            yield from iter_package_files(entry, f"{rel}/")
            continue
        if entry.suffix.lower() in SKIP_SUFFIXES:
            continue
        yield rel, entry


def add_file(tar: tarfile.TarFile, arcname: str, data: bytes, mode: int, mtime: int):
    info = tarfile.TarInfo(arcname)
    info.size = len(data)
    info.mode = mode
    info.mtime = mtime
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    tar.addfile(info, io.BytesIO(data))


def build_app_tgz(mtime: int) -> bytes:
    buffer = io.BytesIO()
    files = 0
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for rel, path in iter_package_files(PKG / "app"):
            data = path.read_bytes()
            if path.suffix.lower() in TEXT_SUFFIXES or path.name == "config":
                data = normalize_text(data)
            mode = 0o755 if rel.startswith("server/garage.py") else 0o644
            add_file(tar, rel, data, mode, mtime)
            files += 1
    raw = buffer.getvalue()
    compressed = gzip.compress(raw, 9, mtime=0)
    log(f"  app.tgz        : {files} 个文件, {len(raw) / 1024:.1f} KB -> {len(compressed) / 1024:.1f} KB")
    return compressed


def build_fpk(meta: dict) -> Path:
    mtime = int(time.mktime(time.strptime("2026-01-01", "%Y-%m-%d")))
    app_tgz = build_app_tgz(mtime)

    DIST.mkdir(parents=True, exist_ok=True)
    # 沿用 fnpack 命名：{appname}_{version}_{platform}.fpk
    target = DIST / f"{meta['appname']}_{meta['version']}_{meta['platform']}.fpk"

    entries = 0
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        # 根级清单文件
        for rel, path in iter_package_files(PKG):
            if rel.startswith("app/"):
                continue
            data = path.read_bytes()
            if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"manifest", "privilege", "resource",
                                                                   "install", "config", "uninstall", "main"}:
                data = normalize_text(data)
            if data.startswith(b"\xef\xbb\xbf"):
                data = data[3:]
            mode = 0o755 if rel in EXEC_FILES else 0o644
            add_file(tar, rel, data, mode, mtime)
            entries += 1
        add_file(tar, "app.tgz", app_tgz, 0o644, mtime)
        entries += 1

    # 固定 gzip 头时间戳，保证同样源码重复构建得到完全相同的包
    target.write_bytes(gzip.compress(buffer.getvalue(), 9, mtime=0))

    log(f"  fpk            : {entries} 个条目, {target.stat().st_size / 1024:.1f} KB")
    return target


def verify(fpk: Path) -> None:
    log("\n[校验] 包内清单")
    with tarfile.open(fpk, "r:gz") as tar:
        names = sorted(tar.getnames())
        for name in names:
            member = tar.getmember(name)
            flag = "x" if member.mode & 0o111 else "-"
            log(f"  {flag} {member.size:>8}  {name}")
        missing = [p for p in REQUIRED if p not in names]
        if "app.tgz" not in names:
            missing.append("app.tgz")
        if missing:
            raise SystemExit("包内缺少：" + ", ".join(missing))
        if any(n.startswith("app/") and n != "app.tgz" for n in names):
            raise SystemExit("app 目录应已压缩为 app.tgz，不应平铺在包内")
        for rel in EXEC_FILES:
            if not tar.getmember(rel).mode & 0o111:
                raise SystemExit(f"{rel} 缺少可执行权限")

        app_bytes = tar.extractfile("app.tgz").read()
        with tarfile.open(fileobj=io.BytesIO(app_bytes), mode="r:gz") as app_tar:
            app_names = app_tar.getnames()
            log(f"\n[校验] app.tgz 内 {len(app_names)} 个文件")
            for name in app_names:
                log(f"  - {name}")
            for need in APP_REQUIRED:
                if need not in app_names:
                    raise SystemExit(f"app.tgz 缺少 {need}")
            sample = app_tar.extractfile("server/garage.py").read()
            if b"\r\n" in sample:
                raise SystemExit("app.tgz 内换行符未规范化为 LF")


def main() -> int:
    log("车库管家 · fpk 构建")
    ensure_icons()
    meta = validate()
    log(f"[1/3] 结构校验通过，版本 {meta['version']}，架构 {meta['platform']}")
    log("[2/3] 打包")
    fpk = build_fpk(meta)
    verify(fpk)
    log(f"\n完成：{fpk}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
