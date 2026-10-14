"""drive_tool — read-only storage contract and in-memory adapter (MODULE-001)."""

from drive_tool.storage import (
    ROOT_ID,
    FileMetadata,
    FileRef,
    InMemoryAdapter,
    IsDirectoryError,
    NotDirectoryError,
    NotFoundError,
    SourceMismatchError,
    StorageAdapter,
    StorageError,
)

__all__ = [
    "ROOT_ID",
    "FileRef",
    "FileMetadata",
    "StorageAdapter",
    "StorageError",
    "SourceMismatchError",
    "NotFoundError",
    "NotDirectoryError",
    "IsDirectoryError",
    "InMemoryAdapter",
]
