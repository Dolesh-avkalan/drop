"""Tests for the MODULE-002 paginated listing helper.

Synthetic fixtures only. Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import dataclasses
import unittest

from drive_tool.listing import MAX_LIMIT, MIN_LIMIT, ListingPage, ListingService
from drive_tool.storage import (
    ROOT_ID,
    FileMetadata,
    FileRef,
    InMemoryAdapter,
    NotDirectoryError,
    NotFoundError,
    SourceMismatchError,
    StorageError,
)

SOURCE = "src-a"

# Names chosen so ASCII sorting is non-trivial: uppercase 'B' (0x42) sorts
# before lowercase 'a' (0x61), and 'Beta.txt' contains no lowercase 'beta'.
FIXTURE_NAMES = [
    "Beta.txt",
    "alpha.txt",
    "beta.txt",
    "delta.txt",
    "epsilon.txt",
    "gamma.txt",
]
SORTED_NAMES = sorted(FIXTURE_NAMES)


def make_adapter() -> InMemoryAdapter:
    return InMemoryAdapter(SOURCE, {name: b"x" for name in FIXTURE_NAMES})


def meta(name: str, source_id: str = SOURCE, file_id: str | None = None) -> FileMetadata:
    return FileMetadata(
        ref=FileRef(source_id, file_id if file_id is not None else name),
        name=name,
        parent_id=ROOT_ID,
        kind="file",
        size_bytes=0,
    )


class FakeAdapter:
    """A StorageAdapter stand-in that counts calls and can raise on demand."""

    def __init__(self, metadata=(), error: BaseException | None = None) -> None:
        self.source_id = "src-fake"
        self.calls = 0
        self._metadata = list(metadata)
        self._error = error

    def list_children(self, parent: FileRef) -> list[FileMetadata]:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return list(self._metadata)

    def stat(self, ref: FileRef) -> FileMetadata:  # pragma: no cover - unused
        raise NotImplementedError

    def read_bytes(self, ref: FileRef) -> bytes:  # pragma: no cover - unused
        raise NotImplementedError


class TestEmptySource(unittest.TestCase):
    def test_empty_source_yields_empty_page(self) -> None:
        adapter = InMemoryAdapter(SOURCE, {})
        page = ListingService(adapter).list_page(FileRef(SOURCE, ROOT_ID))
        self.assertEqual(page.items, ())
        self.assertIsNone(page.next_offset)


class TestPagination(unittest.TestCase):
    """Sorted first/middle/final pages, offset == length, offset > length."""

    def setUp(self) -> None:
        self.service = ListingService(make_adapter())
        self.root = FileRef(SOURCE, ROOT_ID)

    def test_first_page(self) -> None:
        page = self.service.list_page(self.root, limit=2, offset=0)
        self.assertEqual([m.name for m in page.items], SORTED_NAMES[0:2])
        self.assertEqual(page.next_offset, 2)

    def test_middle_page(self) -> None:
        page = self.service.list_page(self.root, limit=2, offset=2)
        self.assertEqual([m.name for m in page.items], SORTED_NAMES[2:4])
        self.assertEqual(page.next_offset, 4)

    def test_final_page(self) -> None:
        page = self.service.list_page(self.root, limit=2, offset=4)
        self.assertEqual([m.name for m in page.items], SORTED_NAMES[4:6])
        self.assertIsNone(page.next_offset)

    def test_offset_equal_to_length(self) -> None:
        page = self.service.list_page(self.root, limit=2, offset=len(SORTED_NAMES))
        self.assertEqual(page.items, ())
        self.assertIsNone(page.next_offset)

    def test_offset_above_length_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.service.list_page(self.root, limit=2, offset=len(SORTED_NAMES) + 1)

    def test_limit_larger_than_remaining(self) -> None:
        page = self.service.list_page(self.root, limit=MAX_LIMIT, offset=0)
        self.assertEqual([m.name for m in page.items], SORTED_NAMES)
        self.assertIsNone(page.next_offset)

    def test_limit_boundaries(self) -> None:
        page_min = self.service.list_page(self.root, limit=MIN_LIMIT, offset=0)
        self.assertEqual(len(page_min.items), 1)
        self.assertEqual(page_min.next_offset, 1)
        page_max = self.service.list_page(self.root, limit=MAX_LIMIT, offset=0)
        self.assertEqual(len(page_max.items), len(SORTED_NAMES))

    def test_next_offset_exact_when_more_remain(self) -> None:
        page = self.service.list_page(self.root, limit=4, offset=0)
        self.assertEqual(page.next_offset, 4)
        page2 = self.service.list_page(self.root, limit=4, offset=4)
        self.assertEqual([m.name for m in page2.items], SORTED_NAMES[4:6])
        self.assertIsNone(page2.next_offset)


class TestSorting(unittest.TestCase):
    def test_sorted_by_name_source_id_file_id(self) -> None:
        # Same name, different source_id: the tie-break must order by source_id.
        adapter = FakeAdapter(
            [meta("dup.txt", "s2"), meta("dup.txt", "s1"), meta("aaa.txt", "s9")]
        )
        page = ListingService(adapter).list_page(FileRef(SOURCE, ROOT_ID))
        self.assertEqual(
            [(m.name, m.ref.source_id) for m in page.items],
            [("aaa.txt", "s9"), ("dup.txt", "s1"), ("dup.txt", "s2")],
        )

    def test_sorted_by_file_id_when_name_and_source_match(self) -> None:
        adapter = FakeAdapter(
            [meta("dup.txt", "s1", "z"), meta("dup.txt", "s1", "a")]
        )
        page = ListingService(adapter).list_page(FileRef(SOURCE, ROOT_ID))
        self.assertEqual([m.ref.file_id for m in page.items], ["a", "z"])


class TestFiltering(unittest.TestCase):
    """Filtering before pagination; case sensitivity; empty filter; no matches."""

    def setUp(self) -> None:
        self.service = ListingService(make_adapter())
        self.root = FileRef(SOURCE, ROOT_ID)

    def test_case_sensitive_filter_excludes_other_case(self) -> None:
        page = self.service.list_page(self.root, name_contains="beta")
        self.assertEqual([m.name for m in page.items], ["beta.txt"])

    def test_case_sensitive_filter_matches_exact_case(self) -> None:
        page = self.service.list_page(self.root, name_contains="Beta")
        self.assertEqual([m.name for m in page.items], ["Beta.txt"])

    def test_uppercase_filter_has_no_matches(self) -> None:
        page = self.service.list_page(self.root, name_contains="BETA")
        self.assertEqual(page.items, ())
        self.assertIsNone(page.next_offset)

    def test_empty_filter_includes_all(self) -> None:
        page = self.service.list_page(self.root, name_contains="", limit=MAX_LIMIT)
        self.assertEqual([m.name for m in page.items], SORTED_NAMES)

    def test_no_matches(self) -> None:
        page = self.service.list_page(self.root, name_contains="zzz")
        self.assertEqual(page.items, ())
        self.assertIsNone(page.next_offset)

    def test_filter_applied_before_pagination(self) -> None:
        # 'a' matches Beta.txt, alpha.txt, beta.txt, delta.txt, gamma.txt (5),
        # but not epsilon.txt. next_offset must reflect the filtered length.
        filtered = ["Beta.txt", "alpha.txt", "beta.txt", "delta.txt", "gamma.txt"]
        page = self.service.list_page(self.root, limit=2, offset=0, name_contains="a")
        self.assertEqual([m.name for m in page.items], filtered[0:2])
        self.assertEqual(page.next_offset, 2)
        last = self.service.list_page(self.root, limit=2, offset=4, name_contains="a")
        self.assertEqual([m.name for m in last.items], filtered[4:5])
        self.assertIsNone(last.next_offset)

    def test_filter_then_offset_equal_filtered_length(self) -> None:
        page = self.service.list_page(
            self.root, limit=2, offset=1, name_contains="beta"
        )
        self.assertEqual(page.items, ())
        self.assertIsNone(page.next_offset)


class TestResultShape(unittest.TestCase):
    def test_items_is_tuple(self) -> None:
        page = ListingService(make_adapter()).list_page(FileRef(SOURCE, ROOT_ID))
        self.assertIsInstance(page.items, tuple)

    def test_page_is_frozen(self) -> None:
        page = ListingService(make_adapter()).list_page(FileRef(SOURCE, ROOT_ID))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            page.next_offset = 5  # type: ignore[misc]

    def test_page_equality(self) -> None:
        service = ListingService(make_adapter())
        a = service.list_page(FileRef(SOURCE, ROOT_ID), limit=2)
        b = service.list_page(FileRef(SOURCE, ROOT_ID), limit=2)
        self.assertEqual(a, b)


class TestValidation(unittest.TestCase):
    """Invalid limit/offset (incl bool, float, str, negative, 0/101) and filter."""

    def setUp(self) -> None:
        self.adapter = FakeAdapter()
        self.service = ListingService(self.adapter)
        self.root = FileRef(SOURCE, ROOT_ID)

    def test_invalid_limit(self) -> None:
        for bad in (0, 101, -1, True, False, 1.5, "5", None, [1]):
            with self.subTest(limit=bad):
                with self.assertRaises(ValueError):
                    self.service.list_page(self.root, limit=bad)

    def test_invalid_offset(self) -> None:
        for bad in (-1, True, False, 1.5, "0", None, [0]):
            with self.subTest(offset=bad):
                with self.assertRaises(ValueError):
                    self.service.list_page(self.root, offset=bad)

    def test_invalid_name_contains(self) -> None:
        for bad in (5, ["a"], b"a", True, 1.0):
            with self.subTest(name_contains=bad):
                with self.assertRaises(ValueError):
                    self.service.list_page(self.root, name_contains=bad)

    def test_valid_arguments_do_not_raise(self) -> None:
        for good_limit in (1, 50, 100):
            with self.subTest(limit=good_limit):
                self.service.list_page(self.root, limit=good_limit)

    def test_valid_offsets_do_not_raise(self) -> None:
        # Three items, so offsets 0..3 are all valid (3 == length -> empty page).
        self.adapter._metadata = [meta("a.txt"), meta("b.txt"), meta("c.txt")]
        for good_offset in (0, 1, 3):
            with self.subTest(offset=good_offset):
                self.service.list_page(self.root, offset=good_offset)


class TestAdapterNotCalledOnInvalidArguments(unittest.TestCase):
    """A fake adapter call counter proves invalid arguments never reach it."""

    def setUp(self) -> None:
        self.adapter = FakeAdapter()
        self.service = ListingService(self.adapter)
        self.root = FileRef(SOURCE, ROOT_ID)

    def test_invalid_limit_does_not_call_adapter(self) -> None:
        with self.assertRaises(ValueError):
            self.service.list_page(self.root, limit=0)
        self.assertEqual(self.adapter.calls, 0)

    def test_invalid_offset_does_not_call_adapter(self) -> None:
        with self.assertRaises(ValueError):
            self.service.list_page(self.root, offset=-1)
        self.assertEqual(self.adapter.calls, 0)

    def test_invalid_filter_does_not_call_adapter(self) -> None:
        with self.assertRaises(ValueError):
            self.service.list_page(self.root, name_contains=5)
        self.assertEqual(self.adapter.calls, 0)

    def test_valid_call_calls_adapter_once(self) -> None:
        self.service.list_page(self.root)
        self.assertEqual(self.adapter.calls, 1)

    def test_offset_above_length_calls_adapter_first(self) -> None:
        # This check needs the listing, so the adapter is consulted once.
        self.adapter._metadata = [meta("one.txt")]
        with self.assertRaises(ValueError):
            self.service.list_page(self.root, offset=5)
        self.assertEqual(self.adapter.calls, 1)


class TestAdapterErrorPropagation(unittest.TestCase):
    """Adapter errors propagate without changing their type."""

    def _assert_propagates(self, error: BaseException) -> None:
        adapter = FakeAdapter(error=error)
        service = ListingService(adapter)
        with self.assertRaises(type(error)) as ctx:
            service.list_page(FileRef(SOURCE, ROOT_ID))
        self.assertIs(ctx.exception, error)

    def test_not_found_propagates(self) -> None:
        self._assert_propagates(NotFoundError("missing"))

    def test_not_directory_propagates(self) -> None:
        self._assert_propagates(NotDirectoryError("not a dir"))

    def test_source_mismatch_propagates(self) -> None:
        self._assert_propagates(SourceMismatchError("wrong source"))

    def test_base_storage_error_propagates(self) -> None:
        self._assert_propagates(StorageError("generic"))


if __name__ == "__main__":
    unittest.main()
