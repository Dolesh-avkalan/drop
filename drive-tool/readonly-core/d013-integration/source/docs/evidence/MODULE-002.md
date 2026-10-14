# MODULE-002 — evidence

Task: MODULE-002 — paginated listing helper
Repository: https://github.com/Dolesh-avkalan/drive-tool
Branch: feature/module-002-listing
Base commit: 194d4ad57de6dd895c6eaaf7faf4d08583eab02b (MODULE-001 tip, not main)
Date (UTC): 2026-10-06 17:12:27
Python: Python 3.12.13

## Files delivered

- drive_tool/listing.py
- tests/test_listing.py
- docs/evidence/MODULE-002.md (this file)

Only these files are added. MODULE-001 files (drive_tool/__init__.py,
drive_tool/storage.py, tests/test_storage.py, docs/evidence/MODULE-001.md)
are unchanged.

## Scope confirmation

Read-only helper over the existing StorageAdapter contract, standard library
only. No connectors, no deployment, no branch merge, no modification of
MODULE-001. Synthetic fixtures only.

## Exact test command

Run from the repository root:

    python3 -m unittest discover -s tests -v

## Real result

Exit status: EXIT=0
Summary line: Ran 71 tests in 0.016s

Note: `unittest -v` writes its report to stderr, so the captured stdout below
is empty by design and the full report appears under stderr. The run includes
the 36 pre-existing MODULE-001 tests plus the new MODULE-002 tests.

### stdout (empty)

```
```

### stderr (full unittest report)

```
test_base_storage_error_propagates (test_listing.TestAdapterErrorPropagation.test_base_storage_error_propagates) ... ok
test_not_directory_propagates (test_listing.TestAdapterErrorPropagation.test_not_directory_propagates) ... ok
test_not_found_propagates (test_listing.TestAdapterErrorPropagation.test_not_found_propagates) ... ok
test_source_mismatch_propagates (test_listing.TestAdapterErrorPropagation.test_source_mismatch_propagates) ... ok
test_invalid_filter_does_not_call_adapter (test_listing.TestAdapterNotCalledOnInvalidArguments.test_invalid_filter_does_not_call_adapter) ... ok
test_invalid_limit_does_not_call_adapter (test_listing.TestAdapterNotCalledOnInvalidArguments.test_invalid_limit_does_not_call_adapter) ... ok
test_invalid_offset_does_not_call_adapter (test_listing.TestAdapterNotCalledOnInvalidArguments.test_invalid_offset_does_not_call_adapter) ... ok
test_offset_above_length_calls_adapter_first (test_listing.TestAdapterNotCalledOnInvalidArguments.test_offset_above_length_calls_adapter_first) ... ok
test_valid_call_calls_adapter_once (test_listing.TestAdapterNotCalledOnInvalidArguments.test_valid_call_calls_adapter_once) ... ok
test_empty_source_yields_empty_page (test_listing.TestEmptySource.test_empty_source_yields_empty_page) ... ok
test_case_sensitive_filter_excludes_other_case (test_listing.TestFiltering.test_case_sensitive_filter_excludes_other_case) ... ok
test_case_sensitive_filter_matches_exact_case (test_listing.TestFiltering.test_case_sensitive_filter_matches_exact_case) ... ok
test_empty_filter_includes_all (test_listing.TestFiltering.test_empty_filter_includes_all) ... ok
test_filter_applied_before_pagination (test_listing.TestFiltering.test_filter_applied_before_pagination) ... ok
test_filter_then_offset_equal_filtered_length (test_listing.TestFiltering.test_filter_then_offset_equal_filtered_length) ... ok
test_no_matches (test_listing.TestFiltering.test_no_matches) ... ok
test_uppercase_filter_has_no_matches (test_listing.TestFiltering.test_uppercase_filter_has_no_matches) ... ok
test_final_page (test_listing.TestPagination.test_final_page) ... ok
test_first_page (test_listing.TestPagination.test_first_page) ... ok
test_limit_boundaries (test_listing.TestPagination.test_limit_boundaries) ... ok
test_limit_larger_than_remaining (test_listing.TestPagination.test_limit_larger_than_remaining) ... ok
test_middle_page (test_listing.TestPagination.test_middle_page) ... ok
test_next_offset_exact_when_more_remain (test_listing.TestPagination.test_next_offset_exact_when_more_remain) ... ok
test_offset_above_length_raises (test_listing.TestPagination.test_offset_above_length_raises) ... ok
test_offset_equal_to_length (test_listing.TestPagination.test_offset_equal_to_length) ... ok
test_items_is_tuple (test_listing.TestResultShape.test_items_is_tuple) ... ok
test_page_equality (test_listing.TestResultShape.test_page_equality) ... ok
test_page_is_frozen (test_listing.TestResultShape.test_page_is_frozen) ... ok
test_sorted_by_file_id_when_name_and_source_match (test_listing.TestSorting.test_sorted_by_file_id_when_name_and_source_match) ... ok
test_sorted_by_name_source_id_file_id (test_listing.TestSorting.test_sorted_by_name_source_id_file_id) ... ok
test_invalid_limit (test_listing.TestValidation.test_invalid_limit) ... ok
test_invalid_name_contains (test_listing.TestValidation.test_invalid_name_contains) ... ok
test_invalid_offset (test_listing.TestValidation.test_invalid_offset) ... ok
test_valid_arguments_do_not_raise (test_listing.TestValidation.test_valid_arguments_do_not_raise) ... ok
test_valid_offsets_do_not_raise (test_listing.TestValidation.test_valid_offsets_do_not_raise) ... ok
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
Ran 71 tests in 0.016s

OK
```

## Coverage against the acceptance criteria

- Empty source; sorted first/middle/final pages; offset equal to length;
  offset above length — TestEmptySource, TestPagination.
- Exact next_offset behaviour and tuple/frozen result — TestPagination,
  TestResultShape.
- Filtering before pagination; case sensitivity; empty filter; no matches —
  TestFiltering.
- Invalid limit/offset including bool, float, str, negative, and limit 0/101 —
  TestValidation.
- Invalid filter type — TestValidation.
- A fake adapter call counter proves invalid arguments do not call the adapter —
  TestAdapterNotCalledOnInvalidArguments.
- Adapter errors propagate without changing their type —
  TestAdapterErrorPropagation.
- Existing 36 MODULE-001 tests still pass — confirmed in the run above.

## Consistency note

This is offset pagination of a fresh listing, not a consistent snapshot. Each
call re-reads `adapter.list_children(parent)`, so files added, removed, or
renamed between calls can shift pages. Opaque durable cursors are out of scope
for this module.

## Limitations

- Execution evidence is from this sandbox (Debian, CPython Python 3.12.13). The brief
  states Python 3.11+ as the minimum; only 3.12 was available to run here.
- Pagination is offset-based over a freshly fetched listing; it is not a
  consistent snapshot across calls.
- The helper is read-only and delegates all source/file resolution and error
  semantics to the adapter; it does not intercept StorageError exceptions.
