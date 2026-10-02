#!/usr/bin/env bash
# Mac/Linux: ./audit.sh  (asks for the URL)  or  ./audit.sh https://site.com --cities "Frisco, TX"
cd "$(dirname "$0")"
python3 -m auditor "$@"
