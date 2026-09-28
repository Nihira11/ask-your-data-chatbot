#!/bin/bash
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo 'Please follow the Python setup steps in README.md first.'
  read -r -p 'Press Return to close.'
  exit 1
fi
exec .venv/bin/python app.py
