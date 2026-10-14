"""Tests for the MODULE-001 storage contract and in-memory adapter.

Synthetic data only. Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import dataclasses
import unittest

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

SOURCE = "src-a"
OTHER_SOURCE = "src-b"

FIXTURES = {
    "alpha.txt": b"hello",
    "empty.bin": b"",
    "zulu.dat": bytes(range(256)),
    "beta.bin": b"\x00\x01\x02\xff",
}


def make_adapter() -> InMemoryAdapter:
    return InMemoryAdapter(SOURCE, dict(FIXTURES))


class TestStat(unittest.TestCase):
    """Criterion 1: root and file stat values, including binary size."""

    def setUp(self) -> None:
        self.adapter = make_adapter()

    def test_root_stat_values(self) -> None:
        meta = self.adapter.stat(FileRef(SOURCE, ROOT_ID))
        self.assertEqual(meta.ref, FileRef(SOURCE, ROOT_ID))
        self.assertEqual(meta.name, "")
        self.assertIsNone(meta.parent_id)
        self.assertEqual(meta.kind, "directory")
        self.assertIsNone(meta.size_bytes)

    def test_file_stat_values(self) -> None:
        meta = self.adapter.stat(FileRef(SOURCE, "alpha.txt"))
        self.assertEqual(meta.ref, FileRef(SOURCE, "alpha.txt"))
        self.assertEqual(meta.name, "alpha.txt")
        self.assertEqual(meta.parent_id, ROOT_ID)
        self.assertEqual(meta.kind, "file")
        self.assertEqual(meta.size_bytes, 5)

    def test_binary_file_size(self) -> None:
        meta = self.adapter.stat(FileRef(SOURCE, "zulu.dat"))
        self.assertEqual(meta.size_bytes, 256)

    def test_empty_file_size(self) -> None:
        meta = self.adapter.stat(FileRef(SOURCE, "empty.bin"))
        self.assertEqual(meta.size_bytes, 0)


class TestListChildren(unittest.TestCase):
    """Criterion 2: deterministic listing order and empty root."""

    def test_listing_is_sorted_by_name(self) -> None:
        adapter = make_adapter()
        names = [m.name for m in adapter.list_children(FileRef(SOURCE, ROOT_ID))]
        self.assertEqual(names, ["alpha.txt", "beta.bin", "empty.bin", "zulu.dat"])

    def test_listing_is_deterministic_across_calls(self) -> None:
        adapter = make_adapter()
        first = adapter.list_children(FileRef(SOURCE, ROOT_ID))
        second = adapter.list_children(FileRef(SOURCE, ROOT_ID))
        self.assertEqual(first, second)

    def test_empty_root(self) -> None:
        adapter = InMemoryAdapter(SOURCE, {})
        self.assertEqual(adapter.list_children(FileRef(SOURCE, ROOT_ID)), [])

    def test_children_metadata_fields(self) -> None:
        adapter = make_adapter()
        children = adapter.list_children(FileRef(SOURCE, ROOT_ID))
        for meta in children:
            self.assertEqual(meta.kind, "file")
            self.assertEqual(meta.parent_id, ROOT_ID)
            self.assertEqual(meta.ref.source_id, SOURCE)


class TestReadBytes(unittest.TestCase):
    """Criterion 3: exact binary and empty-file reads."""

    def setUp(self) -> None:
        self.adapter = make_adapter()

    def test_read_exact_text_bytes(self) -> None:
        self.assertEqual(self.adapter.read_bytes(FileRef(SOURCE, "alpha.txt")), b"hello")

    def test_read_empty_file(self) -> None:
        self.assertEqual(self.adapter.read_bytes(FileRef(SOURCE, "empty.bin")), b"")

    def test_read_binary_file_exact(self) -> None:
        self.assertEqual(
            self.adapter.read_bytes(FileRef(SOURCE, "zulu.dat")), bytes(range(256))
        )

    def test_read_binary_with_nul_and_ff(self) -> None:
        self.assertEqual(
            self.adapter.read_bytes(FileRef(SOURCE, "beta.bin")), b"\x00\x01\x02\xff"
        )


class TestSourceMismatch(unittest.TestCase):
    """Criterion 4: SourceMismatchError from each operation."""

    def setUp(self) -> None:
        self.adapter = make_adapter()

    def test_stat_wrong_source(self) -> None:
        with self.assertRaises(SourceMismatchError):
            self.adapter.stat(FileRef(OTHER_SOURCE, "alpha.txt"))

    def test_list_children_wrong_source(self) -> None:
        with self.assertRaises(SourceMismatchError):
            self.adapter.list_children(FileRef(OTHER_SOURCE, ROOT_ID))

    def test_read_bytes_wrong_source(self) -> None:
        with self.assertRaises(SourceMismatchError):
            self.adapter.read_bytes(FileRef(OTHER_SOURCE, "alpha.txt"))

    def test_wrong_source_precedes_unknown_file_id(self) -> None:
        # Unknown file_id on a wrong source must still be SourceMismatchError.
        with self.assertRaises(SourceMismatchError):
            self.adapter.stat(FileRef(OTHER_SOURCE, "does-not-exist"))
        with self.assertRaises(SourceMismatchError):
            self.adapter.list_children(FileRef(OTHER_SOURCE, "does-not-exist"))
        with self.assertRaises(SourceMismatchError):
            self.adapter.read_bytes(FileRef(OTHER_SOURCE, "does-not-exist"))

    def test_wrong_source_root_ref(self) -> None:
        with self.assertRaises(SourceMismatchError):
            self.adapter.stat(FileRef(OTHER_SOURCE, ROOT_ID))


class TestNotFound(unittest.TestCase):
    """Criterion 5: NotFoundError from each operation on unknown IDs."""

    def setUp(self) -> None:
        self.adapter = make_adapter()

    def test_stat_unknown(self) -> None:
        with self.assertRaises(NotFoundError):
            self.adapter.stat(FileRef(SOURCE, "nope.txt"))

    def test_list_children_unknown(self) -> None:
        with self.assertRaises(NotFoundError):
            self.adapter.list_children(FileRef(SOURCE, "nope.txt"))

    def test_read_bytes_unknown(self) -> None:
        with self.assertRaises(NotFoundError):
            self.adapter.read_bytes(FileRef(SOURCE, "nope.txt"))


class TestDirectoryFileErrors(unittest.TestCase):
    """Criterion 6: correct directory/file operation errors."""

    def setUp(self) -> None:
        self.adapter = make_adapter()

    def test_list_children_on_file_raises_not_directory(self) -> None:
        with self.assertRaises(NotDirectoryError):
            self.adapter.list_children(FileRef(SOURCE, "alpha.txt"))

    def test_read_bytes_on_root_raises_is_directory(self) -> None:
        with self.assertRaises(IsDirectoryError):
            self.adapter.read_bytes(FileRef(SOURCE, ROOT_ID))

    def test_error_hierarchy(self) -> None:
        for exc in (
            SourceMismatchError,
            NotFoundError,
            NotDirectoryError,
            IsDirectoryError,
        ):
            self.assertTrue(issubclass(exc, StorageError))


class TestConstructorValidation(unittest.TestCase):
    """Criterion 7: invalid filename categories, source_id, non-bytes payload."""

    def test_invalid_filenames(self) -> None:
        for bad in (".", "..", "root", "a/b", "a\\b", "a\x00b", "", "a/b/c"):
            with self.subTest(filename=bad):
                with self.assertRaises(ValueError):
                    InMemoryAdapter(SOURCE, {bad: b"x"})

    def test_non_string_filename(self) -> None:
        with self.assertRaises(ValueError):
            InMemoryAdapter(SOURCE, {123: b"x"})  # type: ignore[dict-item]

    def test_invalid_source_id(self) -> None:
        for bad in ("", None, 42):
            with self.subTest(source_id=bad):
                with self.assertRaises(ValueError):
                    InMemoryAdapter(bad, {"alpha.txt": b"x"})  # type: ignore[arg-type]

    def test_non_bytes_payload(self) -> None:
        for bad in ("str", 5, bytearray(b"x"), None, ["x"]):
            with self.subTest(payload=bad):
                with self.assertRaises(ValueError):
                    InMemoryAdapter(SOURCE, {"alpha.txt": bad})  # type: ignore[dict-item]

    def test_files_must_be_mapping(self) -> None:
        with self.assertRaises(ValueError):
            InMemoryAdapter(SOURCE, [("alpha.txt", b"x")])  # type: ignore[arg-type]

    def test_valid_adapter_constructs(self) -> None:
        adapter = InMemoryAdapter(SOURCE, {"alpha.txt": b"hello", "empty.bin": b""})
        self.assertEqual(adapter.source_id, SOURCE)


class TestIsolation(unittest.TestCase):
    """Criterion 8: input mapping mutation does not alter stored fixtures."""

    def test_mutating_input_mapping_after_construction(self) -> None:
        source = {"alpha.txt": b"hello", "beta.bin": b"\x00\x01"}
        adapter = InMemoryAdapter(SOURCE, source)

        source["alpha.txt"] = b"CHANGED"
        source["gamma.txt"] = b"new"
        del source["beta.bin"]

        self.assertEqual(adapter.read_bytes(FileRef(SOURCE, "alpha.txt")), b"hello")
        self.assertEqual(adapter.read_bytes(FileRef(SOURCE, "beta.bin")), b"\x00\x01")
        names = [m.name for m in adapter.list_children(FileRef(SOURCE, ROOT_ID))]
        self.assertEqual(names, ["alpha.txt", "beta.bin"])

    def test_read_returns_are_stable(self) -> None:
        adapter = make_adapter()
        first = adapter.read_bytes(FileRef(SOURCE, "alpha.txt"))
        second = adapter.read_bytes(FileRef(SOURCE, "alpha.txt"))
        self.assertEqual(first, second)
        self.assertEqual(first, b"hello")


class TestFrozen(unittest.TestCase):
    """Criterion 9: frozen metadata/ref reject mutation."""

    def test_fileref_is_frozen(self) -> None:
        ref = FileRef(SOURCE, "alpha.txt")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ref.file_id = "other"  # type: ignore[misc]

    def test_filemetadata_is_frozen(self) -> None:
        meta = make_adapter().stat(FileRef(SOURCE, "alpha.txt"))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            meta.name = "other"  # type: ignore[misc]

    def test_value_equality(self) -> None:
        self.assertEqual(FileRef(SOURCE, "a"), FileRef(SOURCE, "a"))
        self.assertNotEqual(FileRef(SOURCE, "a"), FileRef(SOURCE, "b"))


class TestProtocol(unittest.TestCase):
    """The in-memory adapter satisfies the StorageAdapter protocol."""

    def test_isinstance_protocol(self) -> None:
        self.assertIsInstance(make_adapter(), StorageAdapter)

    def test_metadata_type(self) -> None:
        self.assertIsInstance(
            make_adapter().stat(FileRef(SOURCE, "alpha.txt")), FileMetadata
        )


if __name__ == "__main__":
    unittest.main()
