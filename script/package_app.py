from pathlib import Path
import os
import platform
import plistlib
import shutil
import subprocess


root = Path(os.environ["WECHAT_PROJECT"])
debugger = root / "third_party/WMPFDebugger"
expected_node_version = "23.6.0"
expected_debugger_commit = "1d9f6e03a24dcd39baa223e25a883a85b84bd303"

if platform.machine() != "arm64":
    raise SystemExit("批量取关公众号当前仅支持 Apple Silicon（arm64）构建")
if not (debugger / "node_modules/.bin/tsc").exists():
    raise SystemExit("缺少 WMPFDebugger 依赖；请先在 third_party/WMPFDebugger 中运行 npm install")

node = Path(os.environ.get("WECHAT_NODE_BINARY") or shutil.which("node") or "").resolve()
if not node.is_file():
    raise SystemExit("未找到 Node.js 可执行文件")
node_version = subprocess.check_output([str(node), "-p", "process.versions.node"], text=True).strip()
node_arch = subprocess.check_output([str(node), "-p", "process.arch"], text=True).strip()
if (node_version, node_arch) != (expected_node_version, "arm64"):
    raise SystemExit(
        f"构建需要 Apple Silicon Node.js {expected_node_version}，当前为 {node_version} {node_arch}"
    )

subprocess.run(
    [
        str(debugger / "node_modules/.bin/tsc"),
        "--noEmit",
        "false",
        "--module",
        "commonjs",
        "--rootDir",
        "src",
        "--outDir",
        "build",
    ],
    cwd=debugger,
    check=True,
)
shutil.copytree(debugger / "src/third-party", debugger / "build/third-party", dirs_exist_ok=True)

bundle = root / "dist/批量取关公众号.app"
stage = root / "dist/.Organizer-stage.app"
if stage.exists():
    shutil.rmtree(stage)
contents = stage / "Contents"
macos = contents / "MacOS"
resources = contents / "Resources"
macos.mkdir(parents=True)
resources.mkdir()
shutil.copy2(root / "macapp/.build/debug/WeChatOrganizer", macos / "WeChatOrganizer")
shutil.copytree(root / ".package/WeChatBridge", resources / "backend", symlinks=True)

bridge = resources / "bridge"
bridge.mkdir()
shutil.copy2(root / "assets/AppIcon.icns", resources / "AppIcon.icns")
for name in ["selection.html", "wechat_action.mjs", "compatibility.json"]:
    shutil.copy2(root / name, bridge / name)
shutil.copy2(node, resources / "node")
for part in ["build", "frida"]:
    shutil.copytree(debugger / part, resources / "debugger" / part, symlinks=True)


def ignore(path, names):
    path = Path(path)
    skip = set()
    if path.name == "frida" and path.parent.name == "node_modules":
        skip.update({"deps", "subprojects", "releng", "src", "scripts", "test"})
    if path.name == "build" and path.parent.name == "frida" and path.parent.parent.name == "node_modules":
        skip.update(name for name in names if name not in ("src", "frida_binding.node"))
    if path.name == "node_modules":
        skip.add(".cache")
    return list(skip)


shutil.copytree(debugger / "node_modules", resources / "debugger/node_modules", symlinks=True, ignore=ignore)

# Ship the exact corresponding source and notices beside the executable. This
# also satisfies the source-access expectations for this GPL-covered build.
source = resources / "Source"
source.mkdir()
shutil.copytree(root / "assets", source / "assets")
for name in [
    "selection_server.py",
    "runtime_guard.py",
    "bridge_manager.py",
    "environment_ops.py",
    "helper_signing_change.py",
    "wechat_action.mjs",
    "test_action_requests.mjs",
    "test_selection.py",
    "test_guards.py",
    "selection.html",
    "compatibility.json",
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
]:
    shutil.copy2(root / name, source / name)
shutil.copytree(root / "macapp/Sources", source / "macapp/Sources")
shutil.copy2(root / "macapp/Package.swift", source / "macapp/Package.swift")
shutil.copytree(root / "script", source / "script")
shutil.copytree(root / "docs", source / "docs")
shutil.copytree(
    debugger,
    source / "third_party/WMPFDebugger",
    ignore=shutil.ignore_patterns("node_modules", "build"),
)
shutil.copytree(root / "Licenses", resources / "Licenses")
shutil.copy2(root / "LICENSE", resources / "LICENSE.txt")
shutil.copy2(root / "THIRD_PARTY_NOTICES.md", resources / "THIRD_PARTY_NOTICES.md")

notice = (
    "批量取关公众号 is free software distributed under GPL-2.0-only.\n"
    "WMPFDebugger by evi0s and contributors; GPL-2.0-only.\n"
    "https://github.com/evi0s/WMPFDebugger\n"
    f"Pinned commit: {expected_debugger_commit}\n"
    "Local changes: loopback binding, authenticated CDP relay, health query and graceful shutdown.\n"
    "See THIRD_PARTY_NOTICES.md and Licenses/ for all bundled notices.\n"
    "This Apple Silicon build is ad-hoc signed and has not been notarized.\n"
)
(resources / "NOTICE.txt").write_text(notice)
(source / "NOTICE.txt").write_text(notice)

plist = {
    "CFBundleExecutable": "WeChatOrganizer",
    "CFBundleIdentifier": "com.baiya.WeChatOrganizer",
    "CFBundleName": "批量取关公众号",
    "CFBundleDisplayName": "批量取关公众号",
    "CFBundlePackageType": "APPL",
    "CFBundleVersion": "1",
    "CFBundleShortVersionString": "0.5.0",
    "LSMinimumSystemVersion": "14.0",
    "LSArchitecturePriority": ["arm64"],
    "NSPrincipalClass": "NSApplication",
    "NSAppleEventsUsageDescription": "仅在你选择环境准备或恢复时，请求系统授权修改已验证的微信辅助程序。",
}
plist["CFBundleIconFile"] = "AppIcon"
(contents / "Info.plist").write_bytes(plistlib.dumps(plist))

for path in [resources / "node", resources / "debugger/node_modules/frida/build/frida_binding.node"]:
    subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(path)], check=True, capture_output=True)
subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(stage)], check=True, capture_output=True)
subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(stage)], check=True, capture_output=True)
if bundle.exists():
    shutil.rmtree(bundle)
stage.rename(bundle)
print(bundle)
