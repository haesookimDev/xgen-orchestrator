#!/bin/sh
echo "[sample] status: ok on $(hostname)"
command -v docker >/dev/null 2>&1 && docker ps 2>/dev/null | head -5 || echo "[sample] (no docker)"
