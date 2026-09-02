"""Bulk ZIP intake rejects archive attacks before materializing content."""

import io
import zipfile

import pytest

from termnova.security.archive import read_safe_archive


def _zip(files: dict[str, bytes], compression=zipfile.ZIP_DEFLATED) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def _read(content: bytes, ratio: float = 100.0):
    return read_safe_archive(
        content,
        allowed_extensions={".pdf", ".docx", ".txt", ".md"},
        max_files=10,
        max_uncompressed_bytes=1024 * 1024,
        max_compression_ratio=ratio,
    )


def test_reads_supported_members_without_preserving_archive_paths():
    entries = _read(_zip({"Legal/Vendor A/MSA.txt": b"Agreement text"}))
    assert entries[0].filename == "MSA.txt"
    assert entries[0].content == b"Agreement text"


def test_rejects_path_traversal_and_unsupported_members():
    with pytest.raises(ValueError, match="Unsafe path"):
        _read(_zip({"../outside.txt": b"bad"}))
    with pytest.raises(ValueError, match="Unsupported file"):
        _read(_zip({"payload.exe": b"bad"}))


def test_rejects_zip_bomb_ratio():
    with pytest.raises(ValueError, match="Suspicious compression ratio"):
        _read(_zip({"contract.txt": b"A" * 100_000}), ratio=10)
