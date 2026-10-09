import json
import os
import subprocess
import sys
from pathlib import Path


def test_native_desktop_embedded_browser_and_nfo(tmp_path):
    root = Path(__file__).resolve().parents[1]
    report = tmp_path / "desktop-check.json"
    environment = dict(os.environ)
    environment.pop("JAV_DATA_DATA_DIR", None)
    environment.pop("JAV_DATA_LIBRARY_DIR", None)
    result = subprocess.run(
        [sys.executable, "-m", "jav_data.desktop", "--self-test", str(report)],
        cwd=root,
        env=environment,
        capture_output=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    checked = json.loads(report.read_text(encoding="utf-8"))
    assert checked["ok"] and checked["native_screens"] == 5
    assert checked["embedded_browser"] and checked["cookies"]
    assert checked["japanese_cast"] == 50 and checked["nfo"]
    assert checked["website_sources"] == ["DMM", "MGS"]
