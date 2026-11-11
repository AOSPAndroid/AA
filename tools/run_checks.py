"""Portable developer/CI checks. Never connects to a real Windows target."""
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
for command in ([sys.executable,'tools/check_distribution.py'],[sys.executable,'-m','ruff','check','.']):
    subprocess.run(command,cwd=ROOT,check=True)
