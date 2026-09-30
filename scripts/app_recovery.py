"""Create and restore an offline application backup without overwriting existing state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse


def _database_environment(database_url: str) -> dict[str, str]:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise ValueError("DATABASE_URL must identify a PostgreSQL database")
    env = os.environ.copy()
    env.update(
        {
            "PGHOST": parsed.hostname,
            "PGPORT": str(parsed.port or 5432),
            "PGDATABASE": unquote(parsed.path.lstrip("/")),
            "PGUSER": unquote(parsed.username or ""),
            "PGPASSWORD": unquote(parsed.password or ""),
        }
    )
    query = dict(parse_qsl(parsed.query))
    if query.get("sslmode"):
        env["PGSSLMODE"] = query["sslmode"]
    if query.get("sslrootcert"):
        env["PGSSLROOTCERT"] = unquote(query["sslrootcert"])
    return env


def _run(command: list[str], *, env: dict[str, str], stdout=None) -> None:
    try:
        subprocess.run(command, check=True, env=env, stdout=stdout)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Required PostgreSQL utility is missing: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"{command[0]} failed with exit code {exc.returncode}") from exc


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _object_manifest(root: Path) -> list[dict[str, object]]:
    if not root.is_dir():
        raise ValueError("Object storage root does not exist")
    rows = []
    for path in sorted(root.iterdir()):
        if path.is_symlink() or not path.is_file() or len(path.name) != 64:
            raise ValueError("Object storage must contain only flat SHA-256 object files")
        digest, size = _sha256_file(path)
        if digest != path.name:
            raise ValueError(f"Object integrity check failed for {path.name}")
        rows.append({"key": path.name, "size": size, "sha256": path.name})
    return rows


def backup(database_url: str, object_root: Path, destination: Path) -> Path:
    """Dump PostgreSQL, then copy immutable objects so every DB reference is included."""
    if destination.exists():
        raise ValueError("Backup destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    env = _database_environment(database_url)
    temporary = Path(tempfile.mkdtemp(prefix=".proposal-backup-", dir=destination.parent))
    try:
        _run(
            [
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--file",
                str(temporary / "database.dump"),
            ],
            env=env,
        )
        return _package_dump(temporary / "database.dump", object_root, destination, temporary)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _package_dump(dump_source: Path, object_root: Path, destination: Path, temporary: Path) -> Path:
    if not dump_source.is_file() or dump_source.is_symlink() or dump_source.stat().st_size == 0:
        raise ValueError("Database dump is missing or empty")
    dump = temporary / "database.dump"
    if dump_source.resolve() != dump.resolve():
        shutil.copyfile(dump_source, dump)
    objects_path = temporary / "objects"
    objects_path.mkdir(exist_ok=True)
    objects = _object_manifest(object_root)
    for row in objects:
        shutil.copyfile(object_root / str(row["key"]), objects_path / str(row["key"]))
    dump_hash, dump_size = _sha256_file(dump)
    manifest = {
        "format": 1,
        "database_dump": {
            "path": "database.dump",
            "size": dump_size,
            "sha256": dump_hash,
        },
        "objects": objects,
    }
    (temporary / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, destination)
    if os.name != "nt":
        destination.chmod(0o700)
        for path in destination.rglob("*"):
            if path.is_file():
                path.chmod(0o600)
    return destination


def package_dump(dump_source: Path, object_root: Path, destination: Path) -> Path:
    """Package a dump created by the pinned PostgreSQL service container."""
    if destination.exists():
        raise ValueError("Backup destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".proposal-backup-", dir=destination.parent))
    try:
        return _package_dump(dump_source, object_root, destination, temporary)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _validate_bundle(bundle: Path) -> tuple[Path, list[dict[str, object]]]:
    if bundle.is_symlink() or not bundle.is_dir():
        raise ValueError("Backup bundle must be a real directory")
    manifest_path = bundle / "manifest.json"
    dump_path = bundle / "database.dump"
    objects_path = bundle / "objects"
    if not all(path.is_file() and not path.is_symlink() for path in (manifest_path, dump_path)):
        raise ValueError("Backup bundle is incomplete")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Backup manifest must be an object")
    dump_record = data.get("database_dump")
    if (
        bundle.is_symlink()
        or data.get("format") != 1
        or not isinstance(dump_record, dict)
        or dump_record.get("path") != "database.dump"
    ):
        raise ValueError("Unsupported backup manifest")
    dump_hash, dump_size = _sha256_file(dump_path)
    if dump_size != dump_record.get("size") or dump_hash != dump_record.get("sha256"):
        raise ValueError("Backup database integrity check failed")
    objects = data.get("objects")
    if not isinstance(objects, list) or not objects_path.is_dir() or objects_path.is_symlink():
        raise ValueError("Backup object manifest is invalid")
    expected = set()
    for row in objects:
        key = row.get("key") if isinstance(row, dict) else None
        if (
            not isinstance(key, str)
            or len(key) != 64
            or any(ch not in "0123456789abcdef" for ch in key)
        ):
            raise ValueError("Backup contains an invalid object key")
        path = objects_path / key
        if path.is_symlink() or not path.is_file():
            raise ValueError("Backup is missing an object")
        object_hash, object_size = _sha256_file(path)
        if (
            object_size != row.get("size")
            or object_hash != row.get("sha256")
            or row.get("sha256") != key
        ):
            raise ValueError(f"Backup object integrity check failed for {key}")
        expected.add(key)
    actual = {path.name for path in objects_path.iterdir()}
    if actual != expected:
        raise ValueError("Backup object directory does not match its manifest")
    return dump_path, objects


def _database_is_empty(env: dict[str, str]) -> bool:
    try:
        result = subprocess.run(
            [
                "psql",
                "-X",
                "-A",
                "-t",
                "-c",
                "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema')",
            ],
            check=True,
            env=env,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Required PostgreSQL utility is missing: psql") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"psql failed with exit code {exc.returncode}") from exc
    return result.stdout.strip() == "0"


def install_objects(bundle: Path, object_root: Path) -> int:
    """Install verified objects into an absent/empty application volume."""
    _, objects = _validate_bundle(bundle)
    if object_root.exists() and any(object_root.iterdir()):
        raise ValueError("Restore object root must be absent or empty")
    object_root.mkdir(parents=True, exist_ok=True)
    try:
        for row in objects:
            shutil.copyfile(bundle / "objects" / str(row["key"]), object_root / str(row["key"]))
    except BaseException:
        for row in objects:
            (object_root / str(row["key"])).unlink(missing_ok=True)
        raise
    return len(objects)


def restore(database_url: str, bundle: Path, object_root: Path, *, publication_hold: bool) -> None:
    """Restore into a new empty database and empty object root; never clean existing state."""
    if not publication_hold or os.environ.get("PROPOSAL_PUBLICATION_HOLD", "").lower() != "true":
        raise ValueError(
            "Restore requires both the CLI hold flag and PROPOSAL_PUBLICATION_HOLD=true"
        )
    dump_path, objects = _validate_bundle(bundle)
    if object_root.exists() and any(object_root.iterdir()):
        raise ValueError("Restore object root must be absent or empty")
    env = _database_environment(database_url)
    if not _database_is_empty(env):
        raise ValueError("Restore target database is not empty; use an isolated recovery database")
    install_objects(bundle, object_root)
    try:
        _run(
            [
                "pg_restore",
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
                "--single-transaction",
                "--dbname",
                env["PGDATABASE"],
                str(dump_path),
            ],
            env=env,
        )
    except BaseException:
        for row in objects:
            (object_root / str(row["key"])).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""))
    backup_parser.add_argument("--object-root", type=Path, required=True)
    backup_parser.add_argument("--destination", type=Path, required=True)
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""))
    restore_parser.add_argument("--object-root", type=Path, required=True)
    restore_parser.add_argument("--bundle", type=Path, required=True)
    restore_parser.add_argument("--publication-hold", action="store_true")
    package_parser = subparsers.add_parser("package")
    package_parser.add_argument("--dump-file", type=Path, required=True)
    package_parser.add_argument("--object-root", type=Path, required=True)
    package_parser.add_argument("--destination", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--bundle", type=Path, required=True)
    objects_parser = subparsers.add_parser("objects")
    objects_parser.add_argument("--bundle", type=Path, required=True)
    objects_parser.add_argument("--object-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action not in {"package", "verify", "objects"} and not args.database_url:
        parser.error("set DATABASE_URL or pass --database-url")
    try:
        if args.action == "verify":
            _, objects = _validate_bundle(args.bundle)
            print(f"backup=valid object_count={len(objects)}")
        elif args.action == "objects":
            count = install_objects(args.bundle, args.object_root)
            print(f"objects=restored object_count={count}")
        elif args.action == "package":
            package_dump(args.dump_file, args.object_root, args.destination)
            print(f"backup=packaged object_count={len(_object_manifest(args.object_root))}")
        elif args.action == "backup":
            backup(args.database_url, args.object_root, args.destination)
            print(f"backup=complete object_count={len(_object_manifest(args.object_root))}")
        else:
            restore(
                args.database_url,
                args.bundle,
                args.object_root,
                publication_hold=args.publication_hold,
            )
            print("restore=complete; keep publication hold enabled until reconciliation")
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"recovery error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
