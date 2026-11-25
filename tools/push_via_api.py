#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过 GitHub REST API 推送本地提交，绕开被代理拦截的 git 协议。

背景：本机访问 github.com:443 的 CONNECT 隧道会被代理返回 502，`git push`
不可用；但 api.github.com 可用。本脚本把本地已有的 git 对象（blob / tree /
commit）逐个上传，再更新分支引用，产出与本地完全一致的提交 SHA。

用法:
    python tools/push_via_api.py                 # 推送当前分支到 origin
    python tools/push_via_api.py --dry-run       # 只看要推什么，不发请求
    python tools/push_via_api.py -b main -r origin
    python tools/push_via_api.py --token ghp_xxx # 显式给令牌（否则自动获取）

令牌来源优先级: --token > 环境变量 GITHUB_TOKEN / GH_TOKEN > git credential fill

只依赖 Python 标准库。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_BLOB_BYTES = 90 * 1024 * 1024  # GitHub 单 blob 上限 100MB，留点余量


# --------------------------------------------------------------------------- #
# git 辅助
# --------------------------------------------------------------------------- #
class GitError(RuntimeError):
    pass


def git(*args: str, binary: bool = False, check: bool = True):
    proc = subprocess.run(
        ["git", *args], cwd=REPO_DIR, capture_output=True, stdin=subprocess.DEVNULL
    )
    if check and proc.returncode != 0:
        raise GitError(
            "git %s 失败: %s" % (" ".join(args), proc.stderr.decode("utf-8", "replace").strip())
        )
    if binary:
        return proc.stdout
    return proc.stdout.decode("utf-8", "replace")


def git_ok(*args: str) -> bool:
    proc = subprocess.run(
        ["git", *args], cwd=REPO_DIR, capture_output=True, stdin=subprocess.DEVNULL
    )
    return proc.returncode == 0


def ls_tree(sha: str):
    """返回 [(mode, type, oid, name), ...]"""
    out = git("ls-tree", "-z", sha, binary=True)
    entries = []
    for chunk in out.split(b"\0"):
        if not chunk:
            continue
        meta, name = chunk.split(b"\t", 1)
        mode, otype, oid = meta.split(b" ")
        entries.append((mode.decode(), otype.decode(), oid.decode(), name.decode("utf-8")))
    return entries


def collect_objects(sha: str) -> set[str]:
    """列出该提交可达的全部 blob 与 tree SHA，用于判断远端是否已有。"""
    out = git("ls-tree", "-r", "-t", "-z", "--full-tree", sha, binary=True)
    found = set()
    for chunk in out.split(b"\0"):
        if not chunk:
            continue
        meta = chunk.split(b"\t", 1)[0]
        found.add(meta.split(b" ")[2].decode())
    return found


def commit_object(sha: str):
    """解析原始 commit 对象，保真取回 message 与 author/committer 时间。"""
    raw = git("cat-file", "commit", sha, binary=True)
    head, _, message = raw.partition(b"\n\n")
    info = {"parents": [], "message": message.decode("utf-8")}
    for line in head.decode("utf-8").splitlines():
        if line.startswith("tree "):
            info["tree"] = line[5:]
        elif line.startswith("parent "):
            info["parents"].append(line[7:])
        elif line.startswith("author "):
            info["author"] = parse_ident(line[7:])
        elif line.startswith("committer "):
            info["committer"] = parse_ident(line[10:])
    return info


def parse_ident(raw: str) -> dict:
    """`Name <email> 1700000000 +0800` -> GitHub API 需要的结构。"""
    m = re.match(r"^(.*?) <(.*?)> (\d+) ([+-]\d{4})$", raw.strip())
    if not m:
        raise GitError("无法解析 ident: %r" % raw)
    name, email, ts, tz = m.group(1), m.group(2), int(m.group(3)), m.group(4)
    sign = 1 if tz[0] == "+" else -1
    offset = sign * (int(tz[1:3]) * 3600 + int(tz[3:5]) * 60)
    dt = datetime.fromtimestamp(ts, tz=timezone(timedelta(seconds=offset)))
    return {"name": name, "email": email, "date": dt.isoformat()}


# --------------------------------------------------------------------------- #
# GitHub API
# --------------------------------------------------------------------------- #
class Api:
    def __init__(self, base: str, token: str, dry_run: bool = False):
        self.base = base.rstrip("/")
        self.token = token
        self.dry_run = dry_run
        self.calls = 0

    def request(self, method: str, path: str, body=None):
        if self.dry_run and method != "GET":
            self.calls += 1
            return {"sha": "DRYRUN", "object": {"sha": "DRYRUN"}}
        url = self.base + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("Authorization", "Bearer " + self.token)
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if data:
            req.add_header("Content-Type", "application/json")
        self.calls += 1
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            if exc.code == 422 and "already exists" in detail:
                return {"_already": True}
            raise ApiError(method, path, exc.code, detail)
        except urllib.error.URLError as exc:
            raise ApiError(method, path, None, str(exc.reason))

    def get(self, path):
        return self.request("GET", path)

    def exists(self, path) -> bool:
        try:
            self.request("GET", path)
            return True
        except ApiError as exc:
            if exc.status == 404:
                return False
            raise


class ApiError(RuntimeError):
    def __init__(self, method, path, status, detail):
        self.status = status
        msg = "%s %s -> %s" % (method, path, status if status else "网络错误")
        if status == 403:
            msg += "\n  令牌权限不足：需要 repo 权限（含 contents:write）。" + detail[:300]
        elif status == 404:
            msg += "\n  仓库不存在或令牌无权访问。" + detail[:300]
        elif status:
            msg += "\n  " + detail[:500]
        else:
            msg += "\n  " + detail
        super().__init__(msg)


# --------------------------------------------------------------------------- #
# 取令牌与仓库坐标
# --------------------------------------------------------------------------- #
def resolve_remote(name: str):
    url = git("remote", "get-url", name).strip()
    m = re.match(r"^(?:https?://(?:[^@/]+@)?|git@)([^/:]+)[/:](.+?)(?:\.git)?/?$", url)
    if not m:
        raise SystemExit("无法解析 remote %s 的地址: %s" % (name, url))
    host, path = m.group(1), m.group(2)
    owner, _, repo = path.partition("/")
    return host, owner, repo


def api_base_for(host: str) -> str:
    return "https://api.github.com" if host == "github.com" else "https://%s/api/v3" % host


def resolve_token(explicit: str | None) -> str:
    if explicit:
        return explicit.strip()
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(key):
            return os.environ[key].strip()
    try:
        proc = subprocess.run(
            ["git", "credential", "fill"],
            cwd=REPO_DIR,
            input=b"protocol=https\nhost=github.com\n\n",
            capture_output=True,
        )
        for line in proc.stdout.decode("utf-8", "replace").splitlines():
            if line.startswith("password="):
                return line[len("password="):].strip()
    except OSError:
        pass
    raise SystemExit(
        "未取到 GitHub 令牌。可任选其一：\n"
        "  1) 设置环境变量 GITHUB_TOKEN\n"
        "  2) 让 Windows 凭据管理器记住 github.com 的 PAT\n"
        "  3) 显式传 --token"
    )


# --------------------------------------------------------------------------- #
# 对象上传
# --------------------------------------------------------------------------- #
class Uploader:
    def __init__(self, api: Api, owner: str, repo: str, verbose: bool = True):
        self.api = api
        self.owner = owner
        self.repo = repo
        self.verbose = verbose
        self.blobs_done: set[str] = set()
        self.trees_done: set[str] = set()
        # 远端已确定存在的对象（分支头可达的对象 + 本次已上传），命中即免请求
        self.known_remote: set[str] = set()
        self.blob_uploaded = 0
        self.tree_uploaded = 0

    def log(self, msg: str):
        if self.verbose:
            print(msg, flush=True)

    def has_tree(self, sha: str) -> bool:
        if sha in self.known_remote:
            return True
        if self.api.dry_run:
            return False
        return self.api.exists("/repos/%s/%s/git/trees/%s" % (self.owner, self.repo, sha))

    def ensure_blob(self, sha: str):
        if sha in self.blobs_done or sha in self.known_remote:
            return
        if not self.api.dry_run and self.api.exists(
            "/repos/%s/%s/git/blobs/%s" % (self.owner, self.repo, sha)
        ):
            self.blobs_done.add(sha)
            return
        content = git("cat-file", "blob", sha, binary=True)
        if len(content) > MAX_BLOB_BYTES:
            raise SystemExit("blob %s 超过 90MB，无法走此通道（%d 字节）" % (sha[:8], len(content)))
        self.api.request(
            "POST",
            "/repos/%s/%s/git/blobs" % (self.owner, self.repo),
            {
                "content": base64.b64encode(content).decode("ascii"),
                "encoding": "base64",
            },
        )
        self.blobs_done.add(sha)
        self.blob_uploaded += 1

    def ensure_tree(self, sha: str):
        if sha in self.trees_done or sha in self.known_remote:
            return
        items = []
        for mode, otype, oid, name in ls_tree(sha):
            if otype == "blob":
                self.ensure_blob(oid)
                items.append({"path": name, "mode": mode, "type": "blob", "sha": oid})
            elif otype == "tree":
                self.ensure_tree(oid)
                items.append({"path": name, "mode": "040000", "type": "tree", "sha": oid})
            elif otype == "commit":  # 子模块：远端必须已有该提交
                items.append({"path": name, "mode": "160000", "type": "commit", "sha": oid})
        result = self.api.request(
            "POST",
            "/repos/%s/%s/git/trees" % (self.owner, self.repo),
            {"tree": items},
        )
        got = result.get("sha")
        if got and not self.api.dry_run and got != sha:
            raise SystemExit(
                "tree 校验失败：本地 %s，远端返回 %s。请检查 .gitattributes 过滤规则。" % (sha, got)
            )
        self.trees_done.add(sha)
        self.tree_uploaded += 1
        self.log("    tree %s (%d 项)" % (sha[:8], len(items)))


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="通过 GitHub REST API 推送本地提交")
    parser.add_argument("-r", "--remote", default="origin")
    parser.add_argument("-b", "--branch", default=None, help="默认取当前分支")
    parser.add_argument("--token", default=None)
    parser.add_argument("--force", action="store_true", help="允许覆盖远端已有的分叉提交")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    if not git_ok("rev-parse", "--git-dir"):
        raise SystemExit("当前目录不在 git 仓库内: %s" % REPO_DIR)

    branch = args.branch or git("rev-parse", "--abbrev-ref", "HEAD").strip()
    if branch == "HEAD":
        raise SystemExit("处于游离 HEAD 状态，请先切到具体分支或用 -b 指定。")

    head_sha = git("rev-parse", "HEAD").strip()
    host, owner, repo = resolve_remote(args.remote)
    token = resolve_token(args.token)
    api = Api(api_base_for(host), token, dry_run=args.dry_run)

    print("仓库   %s/%s @ %s" % (owner, repo, host))
    print("分支   %s" % branch)
    print("本地   %s" % head_sha[:10])

    # 1. 远端现状
    remote_sha = None
    try:
        ref = api.get("/repos/%s/%s/git/ref/heads/%s" % (owner, repo, branch))
        remote_sha = ref["object"]["sha"]
    except ApiError as exc:
        if exc.status != 404:
            raise
    print("远端   %s" % (remote_sha[:10] if remote_sha else "（分支不存在）"))

    if remote_sha == head_sha:
        print("\n已是最新，无需推送。")
        return 0

    # 2. 待推提交
    if remote_sha:
        if not git_ok("cat-file", "-e", remote_sha):
            print("\n本地缺少远端提交 %s，先执行 git fetch 再试。" % remote_sha[:10])
            return 2
        if git_ok("merge-base", "--is-ancestor", remote_sha, head_sha):
            todo = [s for s in git("rev-list", "--reverse", "%s..%s" % (remote_sha, head_sha)).split() if s]
        else:
            behind = len(git("rev-list", "%s..%s" % (head_sha, remote_sha)).split())
            if not args.force:
                print(
                    "\n远端有 %d 个本地没有的提交，历史已分叉。\n"
                    "确认要覆盖远端分支可加 --force（会丢失远端那些提交）。" % behind
                )
                return 3
            todo = [s for s in git("rev-list", "--reverse", head_sha).split() if s]
            print("  注意：--force 将覆盖远端 %d 个提交" % behind)
    else:
        todo = [s for s in git("rev-list", "--reverse", head_sha).split() if s]

    print("待推   %d 个提交" % len(todo))
    if args.dry_run:
        for sha in todo:
            print("  %s %s" % (sha[:8], git("log", "-1", "--format=%s", sha).strip()))

    # 3. 逐个提交上传对象
    up = Uploader(api, owner, repo, verbose=not args.quiet)
    if remote_sha:
        up.known_remote = collect_objects(remote_sha)
    for idx, sha in enumerate(todo, 1):
        subject = git("log", "-1", "--format=%s", sha).strip()
        print("[%d/%d] %s %s" % (idx, len(todo), sha[:8], subject), flush=True)

        info = commit_object(sha)
        root_tree = info["tree"]

        if up.has_tree(root_tree):
            print("    tree 已存在，跳过内容上传")
        else:
            up.ensure_tree(root_tree)

        if api.exists("/repos/%s/%s/git/commits/%s" % (owner, repo, sha)):
            print("    commit 已存在")
            up.known_remote |= collect_objects(sha)
            continue

        result = api.request(
            "POST",
            "/repos/%s/%s/git/commits" % (owner, repo),
            {
                "message": info["message"],
                "tree": root_tree,
                "parents": info["parents"],
                "author": info["author"],
                "committer": info["committer"],
            },
        )
        got = result.get("sha")
        if got and not api.dry_run and got != sha:
            raise SystemExit(
                "commit 校验失败：本地 %s，远端 %s。\n"
                "  常见原因：提交里有 GPG 签名（API 创建的提交不带签名）。" % (sha, got)
            )
        if got:
            print("    commit %s" % got[:10])
        up.known_remote |= collect_objects(sha)

    if args.dry_run:
        print("\n[dry-run] 未发起任何写请求；预计 %d 次 API 调用。" % api.calls)
        return 0

    # 4. 更新引用
    ref_path = "/repos/%s/%s/git/refs/heads/%s" % (owner, repo, branch)
    if remote_sha:
        api.request("PATCH", ref_path, {"sha": head_sha, "force": bool(args.force)})
    else:
        api.request(
            "POST",
            "/repos/%s/%s/git/refs" % (owner, repo),
            {"ref": "refs/heads/" + branch, "sha": head_sha},
        )

    # 5. 校验
    final = api.get("/repos/%s/%s/git/ref/heads/%s" % (owner, repo, branch))["object"]["sha"]
    if final != head_sha:
        print("\n推送后校验不一致：远端 %s，本地 %s" % (final, head_sha))
        return 4

    print(
        "\n完成  %s -> %s:%s（上传 blob %d、tree %d、API 调用 %d）"
        % (head_sha[:10], args.remote, branch, up.blob_uploaded, up.tree_uploaded, api.calls)
    )
    print("远端引用已与本地一致。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
