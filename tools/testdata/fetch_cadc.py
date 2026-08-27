from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPOSITORY_ROOT / "tests/data-manifests/cadc-espadons-ad-leo-v1.yaml"
ALLOWED_DATA_HOST = "ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca"


def md5_file(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not payload.get("artifacts"):
        raise ValueError("unsupported or empty CADC manifest")
    product_ids: set[str] = set()
    for artifact in payload["artifacts"]:
        product_id = str(artifact["product_id"])
        if product_id in product_ids:
            raise ValueError(f"duplicate product ID in manifest: {product_id}")
        product_ids.add(product_id)
        checksum = str(artifact["content_checksum"])
        if not checksum.startswith("md5:") or len(checksum) != 36:
            raise ValueError(f"invalid frozen checksum for {product_id}")
        parsed = urlparse(str(artifact["direct_url"]))
        if parsed.scheme != "https" or parsed.hostname != ALLOWED_DATA_HOST:
            raise ValueError(f"non-CADC download URL is forbidden: {artifact['direct_url']}")
    return payload


def validate_external_cache(cache_dir: Path) -> Path:
    resolved = cache_dir.expanduser().resolve()
    repository = REPOSITORY_ROOT.resolve()
    if resolved == repository or repository in resolved.parents:
        raise ValueError("CADC files must be stored outside the source repository")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def select_artifacts(
    manifest: dict[str, Any], *, product_ids: set[str], roles: set[str]
) -> list[dict[str, Any]]:
    selected = []
    for artifact in manifest["artifacts"]:
        if product_ids and artifact["product_id"] not in product_ids:
            continue
        if roles and artifact["role"] not in roles:
            continue
        selected.append(artifact)
    missing = product_ids - {item["product_id"] for item in selected}
    if missing:
        raise ValueError(f"unknown product IDs: {', '.join(sorted(missing))}")
    return selected


def artifact_path(cache_dir: Path, manifest_id: str, artifact: dict[str, Any]) -> Path:
    digest = str(artifact["content_checksum"]).split(":", 1)[1]
    return cache_dir / manifest_id / digest / str(artifact["filename"])


def verify_artifact(path: Path, artifact: dict[str, Any]) -> None:
    expected_size = int(artifact["expected_bytes"])
    expected_md5 = str(artifact["content_checksum"]).split(":", 1)[1]
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size != expected_size:
        raise ValueError(
            f"size mismatch for {artifact['product_id']}: {path.stat().st_size} != {expected_size}"
        )
    actual_md5 = md5_file(path)
    if actual_md5 != expected_md5:
        raise ValueError(
            f"MD5 mismatch for {artifact['product_id']}: {actual_md5} != {expected_md5}"
        )


def _quarantine(path: Path) -> None:
    if path.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path.replace(path.with_name(f"{path.name}.invalid-{stamp}"))


def download_artifact(
    client: httpx.Client,
    artifact: dict[str, Any],
    destination: Path,
    *,
    retries: int,
) -> None:
    if destination.exists():
        verify_artifact(destination, artifact)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(retries + 1):
        offset = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        try:
            with client.stream("GET", artifact["direct_url"], headers=headers) as response:
                response.raise_for_status()
                append = offset > 0 and response.status_code == 206
                if offset and not append:
                    _quarantine(part)
                    offset = 0
                with part.open("ab" if append else "wb") as stream:
                    for block in response.iter_bytes(chunk_size=1024 * 1024):
                        stream.write(block)
                    stream.flush()
                    os.fsync(stream.fileno())
            verify_artifact(part, artifact)
            os.replace(part, destination)
            return
        except (httpx.HTTPError, OSError, ValueError):
            if attempt >= retries:
                _quarantine(part)
                raise
            time.sleep(min(2**attempt, 4))


def write_receipt(
    cache_dir: Path,
    manifest: dict[str, Any],
    artifacts: Iterable[dict[str, Any]],
) -> Path:
    receipt = {
        "manifest_id": manifest["manifest_id"],
        "verified_at": datetime.now(UTC).isoformat(),
        "artifacts": [
            {
                "product_id": item["product_id"],
                "content_checksum": item["content_checksum"],
                "expected_bytes": item["expected_bytes"],
            }
            for item in artifacts
        ],
    }
    destination = cache_dir / manifest["manifest_id"] / "receipt.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".json.part")
    temporary.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    os.replace(temporary, destination)
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch the frozen public CADC ESPaDOnS regression set"
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=os.environ.get("SPRITE_TESTDATA_DIR"),
        help="external cache root; or set SPRITE_TESTDATA_DIR",
    )
    parser.add_argument("--product-id", action="append", default=[])
    parser.add_argument("--role", action="append", default=[])
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--retries", type=int, default=3)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.cache_dir is None:
        raise SystemExit("--cache-dir or SPRITE_TESTDATA_DIR is required")
    manifest = load_manifest(args.manifest.resolve())
    cache_dir = validate_external_cache(args.cache_dir)
    artifacts = select_artifacts(
        manifest,
        product_ids=set(args.product_id),
        roles=set(args.role),
    )
    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(120.0)) as client:
        for artifact in artifacts:
            path = artifact_path(cache_dir, manifest["manifest_id"], artifact)
            if args.verify_only:
                verify_artifact(path, artifact)
            else:
                download_artifact(client, artifact, path, retries=max(0, args.retries))
            print(f"verified {artifact['product_id']} -> {path}")
    receipt = write_receipt(cache_dir, manifest, artifacts)
    print(f"receipt {receipt}")


if __name__ == "__main__":
    main()
