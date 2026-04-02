#!/bin/bash
cd /Users/leonardholler/Downloads/projects/malibu-agent
export PYTHONPATH=/Users/leonardholler/Downloads/projects/malibu-agent
exec python3 -m streamlit run /Users/leonardholler/Downloads/projects/malibu-agent/app.py \
  --server.headless true \
  --server.port "${PORT:-8501}" \
  --server.fileWatcherType none
