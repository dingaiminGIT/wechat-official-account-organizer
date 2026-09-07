#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mode="${1:---run}"
case "$mode" in --run|--build-only|--verify|--debug|--logs) ;; *) exit 2;; esac
project="$PWD"
if pgrep -x WeChatOrganizer >/dev/null; then
  osascript -e 'tell application id "com.baiya.WeChatOrganizer" to quit'
  for ((attempt=0;attempt<130;attempt++)); do pgrep -x WeChatOrganizer >/dev/null || break; sleep 1; done
  if pgrep -x WeChatOrganizer >/dev/null; then echo 'Application is still finishing its operation'; exit 1; fi
fi
(cd macapp && swift build)
.build-env/bin/pyinstaller --noconfirm --clean --onedir --name WeChatBridge --distpath .package --workpath .build-freeze --specpath .build-freeze selection_server.py > .build-freeze.log 2>&1
WECHAT_PROJECT="$project" python3 script/package_app.py
bundle="$project/dist/公众号整理.app"
if [[ "$mode" == --build-only ]]; then exit 0; fi
if [[ "$mode" == --debug ]]; then exec lldb "$bundle/Contents/MacOS/WeChatOrganizer"; fi
open "$bundle"
if [[ "$mode" == --verify ]]; then sleep 2; pgrep -x WeChatOrganizer; fi
if [[ "$mode" == --logs ]]; then exec log stream --info --predicate 'process == "WeChatOrganizer"'; fi
