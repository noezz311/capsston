#!/usr/bin/env bash
set -e
cd /home/lisa/capsston
set -a
source ./runtime.env
set +a
exec .venv/bin/python -u main1.py
