"""Package only tracked integration files and the license for a version tag."""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile


def main(tag):
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise SystemExit("Expected a release tag such as v0.3.0")
    version = tag[1:]
    manifest_path = "custom_components/superwise/manifest.json"
    manifest = json.loads(
        subprocess.check_output(["git", "show", f"HEAD:{manifest_path}"])
    )
    if manifest["version"] != version:
        raise SystemExit("Tag and integration version do not match")
    if not Path(f"docs/releases/{version}.md").is_file():
        raise SystemExit("Release notes are missing")

    paths = ["custom_components/superwise", "LICENSE"]
    expected = set(
        subprocess.check_output(
            ["git", "ls-files", "--", *paths], text=True
        ).splitlines()
    )
    output = Path("dist")
    output.mkdir(exist_ok=True)
    archive = output / "superwise.zip"
    subprocess.run(
        ["git", "archive", "--format=zip", f"--output={archive}", "HEAD", *paths],
        check=True,
    )
    with ZipFile(archive) as package:
        actual = {name for name in package.namelist() if not name.endswith("/")}
        if package.testzip() is not None or actual != expected:
            raise SystemExit("Release archive failed its content check")
        if json.loads(package.read(manifest_path))["version"] != version:
            raise SystemExit("Packaged version does not match the release")

    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "SHA256SUMS").write_text(f"{checksum}  {archive.name}\n")
    print(f"Packaged {len(actual)} files for {tag}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: build_release.py vVERSION")
    main(sys.argv[1])
