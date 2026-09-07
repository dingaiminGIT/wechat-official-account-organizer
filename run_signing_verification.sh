#!/bin/bash
# Run in the user's Terminal so macOS can attribute App Management consent.
set -euo pipefail
cd /Users/dingaimin/tool
result=wechat-unfollow-bridge/.runtime/helper-signing-change/terminal-result.json
printf '微信公众号列表读取验证：仅应用已备份的网页子程序签名改动。\n'
printf '如提示密码，请输入本机管理员密码（输入时不显示字符）。\n'
sudo -v
/usr/bin/osascript -e 'tell application "WeChat" to quit' || true
/usr/bin/python3 - <<'PY'
import os,signal,subprocess,time
for line in subprocess.check_output(['ps','-axo','pid=,comm='],text=True).splitlines():
    parts=line.strip().split(None,1)
    if len(parts)==2 and parts[1]=='/Applications/WeChat.app/Contents/MacOS/WeChat':
        try:os.kill(int(parts[0]),signal.SIGTERM)
        except ProcessLookupError:pass
time.sleep(2)
PY
if sudo -n /usr/bin/python3 wechat-unfollow-bridge/helper_signing_change.py apply > "$result" 2>&1; then
  printf '\n签名改动已完成，正在重新打开微信。\n'
else
  printf '\n改动没有完成，详情如下；正在重新打开微信。\n'
  cat "$result"
fi
/usr/bin/open -a WeChat
printf '\n可以保留此窗口，Codex 会读取结果并继续验证。\n'
