"""Fail-closed ZIP inventory validation without extracting paths to disk."""

import io
import stat
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class ArchiveEntry:
    filename: str
    content: bytes


def read_safe_archive(
    content: bytes,
    *,
    allowed_extensions: set[str],
    max_files: int,
    max_uncompressed_bytes: int,
    max_compression_ratio: float,
) -> list[ArchiveEntry]:
    """Validate traversal, encryption, links, size, and compression ratio before reading."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ValueError("Uploaded bulk file is not a valid ZIP archive") from exc
    infos = [item for item in archive.infolist() if not item.is_dir()]
    if not infos:
        raise ValueError("ZIP archive contains no files")
    if len(infos) > max_files:
        raise ValueError(f"ZIP archive exceeds the {max_files} file limit")
    total_size = sum(item.file_size for item in infos)
    if total_size > max_uncompressed_bytes:
        raise ValueError("ZIP archive exceeds the uncompressed size limit")
    entries: list[ArchiveEntry] = []
    seen_names: set[str] = set()
    for item in infos:
        path = PurePosixPath(item.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Unsafe path in ZIP archive: {item.filename}")
        mode = item.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            raise ValueError(f"Symbolic links are not allowed in ZIP archives: {item.filename}")
        if item.flag_bits & 0x1:
            raise ValueError(f"Encrypted ZIP member requires manual review: {item.filename}")
        suffix = path.suffix.lower()
        if suffix not in allowed_extensions:
            raise ValueError(f"Unsupported file in ZIP archive: {item.filename}")
        compressed = max(item.compress_size, 1)
        if item.file_size / compressed > max_compression_ratio:
            raise ValueError(f"Suspicious compression ratio for ZIP member: {item.filename}")
        safe_name = path.name
        if safe_name in seen_names:
            raise ValueError(f"Duplicate filename in ZIP archive: {safe_name}")
        seen_names.add(safe_name)
        with archive.open(item, "r") as member:
            body = member.read(item.file_size + 1)
        if len(body) != item.file_size:
            raise ValueError(f"ZIP member size changed while reading: {item.filename}")
        entries.append(ArchiveEntry(filename=safe_name, content=body))
    archive.close()
    return entries
