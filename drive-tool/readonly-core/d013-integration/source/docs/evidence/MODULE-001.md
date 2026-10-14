# MODULE-001 — evidence

Task: MODULE-001 — minimal storage contract and in-memory adapter
Repository: https://github.com/Dolesh-avkalan/drive-tool
Branch: feature/module-001-storage-contract
Base commit: ea742e3f489f7e4b324fa5dda477c6304eefafa8
Date (UTC): 2026-10-06 16:55:09
Python: Python 3.12.13

## Files delivered

- drive_tool/__init__.py
- drive_tool/storage.py
- tests/test_storage.py
- docs/evidence/MODULE-001.md (this file)

No other files were modified. README.md and other modules were left untouched.

## Scope confirmation

Read-only storage contract plus an in-memory adapter, standard library only.
No HTTP server, OAuth, credentials, downloads, filesystem adapter, writes,
deletions, deployment, or service changes. Synthetic fixtures only; no real
user files were accessed.

## Exact test command

Run from the repository root:

    python3 -m unittest discover -s tests -v

## Real result

Exit status: EXIT=0

Note: `unittest -v` writes its report to stderr, so the captured stdout below
is empty by design and the full report appears under stderr.

### stdout (empty)

```
```

### stderr (full unittest report)

```
test_files_must_be_mapping (test_storage.TestConstructorValidation.test_files_must_be_mapping) ... ok
test_invalid_filenames (test_storage.TestConstructorValidation.test_invalid_filenames) ... ok
test_invalid_source_id (test_storage.TestConstructorValidation.test_invalid_source_id) ... ok
test_non_bytes_payload (test_storage.TestConstructorValidation.test_non_bytes_payload) ... ok
test_non_string_filename (test_storage.TestConstructorValidation.test_non_string_filename) ... ok
test_valid_adapter_constructs (test_storage.TestConstructorValidation.test_valid_adapter_constructs) ... ok
test_error_hierarchy (test_storage.TestDirectoryFileErrors.test_error_hierarchy) ... ok
test_list_children_on_file_raises_not_directory (test_storage.TestDirectoryFileErrors.test_list_children_on_file_raises_not_directory) ... ok
test_read_bytes_on_root_raises_is_directory (test_storage.TestDirectoryFileErrors.test_read_bytes_on_root_raises_is_directory) ... ok
test_filemetadata_is_frozen (test_storage.TestFrozen.test_filemetadata_is_frozen) ... ok
test_fileref_is_frozen (test_storage.TestFrozen.test_fileref_is_frozen) ... ok
test_value_equality (test_storage.TestFrozen.test_value_equality) ... ok
test_mutating_input_mapping_after_construction (test_storage.TestIsolation.test_mutating_input_mapping_after_construction) ... ok
test_read_returns_are_stable (test_storage.TestIsolation.test_read_returns_are_stable) ... ok
test_children_metadata_fields (test_storage.TestListChildren.test_children_metadata_fields) ... ok
test_empty_root (test_storage.TestListChildren.test_empty_root) ... ok
test_listing_is_deterministic_across_calls (test_storage.TestListChildren.test_listing_is_deterministic_across_calls) ... ok
test_listing_is_sorted_by_name (test_storage.TestListChildren.test_listing_is_sorted_by_name) ... ok
test_list_children_unknown (test_storage.TestNotFound.test_list_children_unknown) ... ok
test_read_bytes_unknown (test_storage.TestNotFound.test_read_bytes_unknown) ... ok
test_stat_unknown (test_storage.TestNotFound.test_stat_unknown) ... ok
test_isinstance_protocol (test_storage.TestProtocol.test_isinstance_protocol) ... ok
test_metadata_type (test_storage.TestProtocol.test_metadata_type) ... ok
test_read_binary_file_exact (test_storage.TestReadBytes.test_read_binary_file_exact) ... ok
test_read_binary_with_nul_and_ff (test_storage.TestReadBytes.test_read_binary_with_nul_and_ff) ... ok
test_read_empty_file (test_storage.TestReadBytes.test_read_empty_file) ... ok
test_read_exact_text_bytes (test_storage.TestReadBytes.test_read_exact_text_bytes) ... ok
test_list_children_wrong_source (test_storage.TestSourceMismatch.test_list_children_wrong_source) ... ok
test_read_bytes_wrong_source (test_storage.TestSourceMismatch.test_read_bytes_wrong_source) ... ok
test_stat_wrong_source (test_storage.TestSourceMismatch.test_stat_wrong_source) ... ok
test_wrong_source_precedes_unknown_file_id (test_storage.TestSourceMismatch.test_wrong_source_precedes_unknown_file_id) ... ok
test_wrong_source_root_ref (test_storage.TestSourceMismatch.test_wrong_source_root_ref) ... ok
test_binary_file_size (test_storage.TestStat.test_binary_file_size) ... ok
test_empty_file_size (test_storage.TestStat.test_empty_file_size) ... ok
test_file_stat_values (test_storage.TestStat.test_file_stat_values) ... ok
test_root_stat_values (test_storage.TestStat.test_root_stat_values) ... ok

----------------------------------------------------------------------
Ran 36 tests in 0.008s

OK
```

## Coverage against the acceptance criteria

1. Root and file stat values, including binary size — TestStat.
2. Deterministic listing order and empty root — TestListChildren.
3. Exact binary and empty-file reads — TestReadBytes.
4. SourceMismatchError from each operation, including an unknown file_id on a
   wrong source — TestSourceMismatch.
5. NotFoundError from each operation on unknown IDs — TestNotFound.
6. Correct directory/file operation errors — TestDirectoryFileErrors.
7. Every invalid filename category, invalid source_id, and non-bytes payload —
   TestConstructorValidation.
8. Input mapping mutation does not alter stored fixtures — TestIsolation.
9. Frozen metadata/ref reject mutation — TestFrozen.

Result: 36 tests, all passing, exit status 0.

## Limitations

- The tests exercise the in-memory adapter only; no filesystem or Google Drive
  adapter exists in this module, by design.
- Byte payloads are limited to `bytes`; `bytearray`/`memoryview` are rejected as
  non-bytes, matching the brief's "non-bytes payloads" rule.
- Only flat fixtures under a single synthetic root are supported; nesting,
  listing pagination, and search are later modules.
- Execution evidence above is from this sandbox (Debian, CPython Python 3.12.13).
  Python 3.11 is the stated minimum; only 3.12 was available to run here.
