#!/bin/zsh
# ダブルクリックでセンサー配置アプリを起動します（止めるときはこの画面を閉じる）
cd "$(dirname "$0")"
../.venv/bin/streamlit run app.py --server.headless true &
sleep 4
open http://localhost:8501
wait
