#!/bin/zsh
cd "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  runtime=""
  for candidate in "$HOME/.local/bin/python3.13" python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; exit(sys.version_info < (3,10))'; then
      runtime="$candidate"
      break
    fi
  done
  if [[ -z "$runtime" ]]; then
    print "请先安装 Python 3.10 或更高版本。"
    read -r "reply?按回车退出"
    exit 1
  fi
  "$runtime" -m venv .venv || exit 1
fi
if ! .venv/bin/python -c 'import yt_dlp, playwright' 2>/dev/null; then
  .venv/bin/python -m pip install -r requirements.txt || exit 1
fi
if ! .venv/bin/python -c 'from collector import browser_ready; exit(not browser_ready())'; then
  .venv/bin/python -m playwright install chromium || exit 1
fi
.venv/bin/python app.py
