"""Validate and archive a fresh Windows release without personal application data."""

import argparse
import hashlib
import json
import shutil
import subprocess
import tomllib
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def package_release(folder, version):
    project = Path(__file__).resolve().parents[1]
    folder = folder.resolve()
    if not folder.is_relative_to(project / "portable") or folder.name != "jav-data":
        raise ValueError("Use a separate fresh jav-data folder inside portable/")
    if not (folder / "jav-data.exe").is_file() or not (folder / "_internal").is_dir():
        raise ValueError("The portable application and runtime must exist")
    storage = tomllib.loads((folder / "config.toml").read_text(encoding="utf-8"))
    if storage != {"storage": {"data_dir": "data", "library_dir": "library"}}:
        raise ValueError("Release configuration must use the clean default storage paths")
    for name in ("data", "library"):
        path = folder / name
        if path.exists() and any(path.iterdir()):
            raise ValueError(f"Refusing to package a populated {name} folder")
    forbidden = {"browser-session.json", "runtime.json", "metadata.json", "movie.nfo"}
    for path in folder.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Release must not contain links: {path.name}")
        if path.is_file() and (
            path.name in forbidden or path.suffix.lower() in {".sqlite3", ".db", ".log"}
        ):
            raise ValueError(f"Personal application file found: {path.name}")
    shutil.copy2(project / "README.md", folder / "README.md")
    shutil.copy2(project / "THIRD_PARTY_NOTICES.md", folder / "THIRD_PARTY_NOTICES.md")
    shutil.copytree(project / "docs", folder / "docs", dirs_exist_ok=True)
    for name in ("data", "library"):
        (folder / name).mkdir(exist_ok=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project, text=True).strip()
    files = sorted(path for path in folder.rglob("*") if path.is_file())
    manifest = {
        "application": "jav-data",
        "version": version,
        "platform": "windows-x64",
        "source_commit": commit,
        "packaged_at_utc": datetime.now(timezone.utc).isoformat(),
        "clean_library": True,
        "files": {path.relative_to(folder).as_posix(): sha256(path) for path in files},
    }
    (folder / "RELEASE-MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    output = project / "dist" / "releases"
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"jav-data-v{version}-windows-x64.zip"
    if archive.exists():
        raise ValueError("Release ZIP already exists; choose a new version or output")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        for path in sorted(folder.rglob("*")):
            relative = path.relative_to(folder.parent).as_posix()
            if path.is_file():
                package.write(path, relative)
            elif not any(path.iterdir()):
                package.writestr(relative + "/", b"")
    with zipfile.ZipFile(archive) as package:
        if failed := package.testzip():
            raise ValueError(f"Archive integrity failure: {failed}")
    checksum = output / "SHA256SUMS.txt"
    checksum.write_text(f"{sha256(archive)}  {archive.name}\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "archive": str(archive),
                "size_mb": round(archive.stat().st_size / 1048576, 1),
                "source_commit": commit,
                "checksum": str(checksum),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", required=True, type=Path)
    parser.add_argument("--version", required=True)
    arguments = parser.parse_args()
    package_release(arguments.folder, arguments.version)
