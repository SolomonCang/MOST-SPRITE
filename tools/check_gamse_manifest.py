from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
    mapped_targets: set[Path] = set()
    for entry in manifest["derived_files"]:
        _validate_source(entry["upstream_path"], entry["upstream_sha256"])
        for source in entry.get("upstream_additional", []):
            _validate_source(source["path"], source["sha256"])
        for asset in entry.get("upstream_assets", []):
            _validate_asset(asset)
        target = Path(entry["sprite_path"])
        if target in mapped_targets:
            raise SystemExit(f"derived source appears more than once in manifest: {target}")
        mapped_targets.add(target)
        if sha256(target) != entry["sprite_sha256"]:
            raise SystemExit(f"derived source hash changed without manifest review: {target}")
    commit = manifest["upstream"]["commit"]
    audited_roots = (
        Path("backend/src/most_sprite/pipeline/echelle"),
        Path("backend/src/most_sprite/pipeline/instruments"),
        Path("backend/src/most_sprite/pipeline/wavelength"),
    )
    for root in audited_roots:
        for target in root.glob("*.py"):
            if commit in target.read_text(errors="ignore") and target not in mapped_targets:
                raise SystemExit(f"GAMSE-derived source is missing from manifest: {target}")


def _validate_asset(asset: Any) -> None:
    if not isinstance(asset, dict):
        raise SystemExit(f"invalid upstream asset declaration: {asset!r}")
    uri = asset.get("uri")
    parsed = urlparse(uri) if isinstance(uri, str) else None
    allowed_hosts = {
        "gamse-bj.s3.cn-north-1.amazonaws.com.cn",
        "gamse.s3.cn-north-1.amazonaws.com.cn",
    }
    if (
        parsed is None
        or parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts
        or not parsed.path
    ):
        raise SystemExit(f"invalid immutable GAMSE asset URI: {uri!r}")
    _validate_hex_digest(asset.get("md5"), 32, f"MD5 for {uri}")
    _validate_hex_digest(asset.get("sha256"), 64, f"SHA-256 for {uri}")
    role = asset.get("role")
    if not isinstance(role, str) or not role.strip():
        raise SystemExit(f"invalid role for upstream asset {uri}")


def _validate_source(path: Any, digest: Any) -> None:
    if not isinstance(path, str) or not path.startswith("gamse/"):
        raise SystemExit(f"invalid upstream GAMSE path: {path!r}")
    _validate_hex_digest(digest, 64, f"upstream hash for {path}")


def _validate_hex_digest(value: Any, length: int, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SystemExit(f"invalid {label}")


if __name__ == "__main__":
    main()
