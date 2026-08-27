from __future__ import annotations

import hashlib
from pathlib import Path

import yaml


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    manifest = yaml.safe_load(Path("third_party/gamse-source-manifest.yaml").read_text())
    license_path = Path(manifest["upstream"]["license_file"])
    if sha256(license_path) != manifest["upstream"]["license_sha256"]:
        raise SystemExit("retained GAMSE license hash does not match the manifest")
    for entry in manifest["derived_files"]:
        target = Path(entry["sprite_path"])
        if sha256(target) != entry["sprite_sha256"]:
            raise SystemExit(f"derived source hash changed without manifest review: {target}")


if __name__ == "__main__":
    main()
