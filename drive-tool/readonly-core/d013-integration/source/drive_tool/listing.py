"""Offset-paginated listing helper over the storage contract.

MODULE-002: a small read-only helper layered on the existing ``StorageAdapter``
contract. It adds no connectors and does not modify MODULE-001.

Consistency note
----------------
This is *offset pagination of a fresh listing*, not a consistent snapshot.
Each call re-reads ``adapter.list_children(parent)``, so if files are added,
removed, or renamed between calls, previously returned offsets can shift and a
page may repeat or skip items. Opaque, durable cursors that survive mutation
are explicitly out of scope for this module.

Python 3.11+, standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass

from drive_tool.storage import FileMetadata, FileRef, StorageAdapter

__all__ = ["ListingPage", "ListingService", "MIN_LIMIT", "MAX_LIMIT"]

MIN_LIMIT = 1
MAX_LIMIT = 100


@dataclass(frozen=True)
class ListingPage:
    """One page of listing results.

    ``items`` is an immutable tuple of metadata in sorted order.
    ``next_offset`` is the offset to pass for the next page, or ``None`` when
    the listing is exhausted.
    """

    items: tuple[FileMetadata, ...]
    next_offset: int | None


def _validate_limit(limit: object) -> None:
    # bool is a subclass of int, so reject it explicitly before the int check.
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError(f"limit must be an int, got {type(limit).__name__}")
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise ValueError(f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}, got {limit}")


def _validate_offset(offset: object) -> None:
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise ValueError(f"offset must be an int, got {type(offset).__name__}")
    if offset < 0:
        raise ValueError(f"offset must be >= 0, got {offset}")


def _validate_name_contains(name_contains: object) -> None:
    if name_contains is not None and not isinstance(name_contains, str):
        raise ValueError(
            f"name_contains must be None or str, got {type(name_contains).__name__}"
        )


class ListingService:
    """Read-only paginated listing over a ``StorageAdapter``."""

    def __init__(self, adapter: StorageAdapter) -> None:
        self._adapter = adapter

    def list_page(
        self,
        parent: FileRef,
        *,
        limit: int = 50,
        offset: int = 0,
        name_contains: str | None = None,
    ) -> ListingPage:
        """Return one page of the sorted, optionally filtered children of ``parent``.

        Arguments are validated before the adapter is called, so invalid input
        never reaches the adapter. Ordering is by ``(name, source_id, file_id)``.
        Filtering is a case-sensitive substring match applied before pagination.
        """
        # Validate everything first: bad arguments must not touch the adapter.
        _validate_limit(limit)
        _validate_offset(offset)
        _validate_name_contains(name_contains)

        # Fresh listing each call; copy before sorting so the adapter's own
        # return value is never mutated.
        items = list(self._adapter.list_children(parent))
        items.sort(key=lambda meta: (meta.name, meta.ref.source_id, meta.ref.file_id))

        if name_contains is not None:
            items = [meta for meta in items if name_contains in meta.name]

        total = len(items)
        if offset > total:
            raise ValueError(
                f"offset {offset} is greater than the filtered length {total}"
            )

        window = items[offset : offset + limit]
        end = offset + len(window)
        next_offset = end if end < total else None
        return ListingPage(items=tuple(window), next_offset=next_offset)
