# MODULE-001 — minimal storage contract and in-memory adapter

Director: Codex. Owner: Dolesh. Implementer: Sarvam in the browser.
Repository: https://github.com/Dolesh-avkalan/drive-tool
Task ID: MODULE-001
Branch: feature/module-001-storage-contract

## Goal and boundaries
Build the smallest useful first module for an agent storage tool: a read-only Python storage contract and in-memory adapter. Later modules connect Google Drive and configured local folders; this task does neither.
Python 3.11+, standard library only. No HTTP server, OAuth, credentials, downloads, filesystem adapter, writes, deletions, deployment, or service changes. Do not access any real user files.
This brief is authoritative for this module. The repo README explains the larger plan; do not implement the whole plan.

## Exact deliverables
- drive_tool/__init__.py
- drive_tool/storage.py
- tests/test_storage.py
- docs/evidence/MODULE-001.md
Do not edit README.md or other modules.

## Interface
Use a frozen dataclass FileRef(source_id: str, file_id: str).
Use a frozen dataclass FileMetadata(ref: FileRef, name: str, parent_id: str | None, kind: str, size_bytes: int | None).
Define a StorageAdapter protocol with:
- stat(ref: FileRef) -> FileMetadata
- list_children(parent: FileRef) -> list[FileMetadata]
- read_bytes(ref: FileRef) -> bytes
Define StorageError and specific subclasses SourceMismatchError, NotFoundError, NotDirectoryError, IsDirectoryError.

InMemoryAdapter(source_id: str, files: dict[str, bytes]) accepts flat fixture files keyed by filename, for example {"alpha.txt": b"hello", "empty.bin": b""}.
The synthetic root is FileRef(source_id, "root").
Each filename is its file_id. Validate filenames: nonempty strings; reject ".", "..", "root", slash, backslash, and NUL. Reject empty source_id and non-bytes payloads. Invalid constructor input raises ValueError.
Copy the input mapping at construction so later external changes do not change the adapter.
Root metadata: name="", parent_id=None, kind="directory", size_bytes=None.
File metadata: name=filename, parent_id="root", kind="file", size_bytes=len(payload).
list_children(root) returns all file metadata sorted by name. list_children(file) raises NotDirectoryError.
read_bytes(file) returns its exact bytes, including empty/binary content. read_bytes(root) raises IsDirectoryError.
All methods reject a mismatched source_id before checking file_id. Unknown file_id raises NotFoundError.

## Acceptance criteria and tests
Use unittest with actual assertions for:
1. Root and file stat values, including binary size.
2. Deterministic listing order and empty root.
3. Exact binary and empty-file reads.
4. SourceMismatchError from each operation, including an unknown file_id on a wrong source.
5. NotFoundError from each operation on unknown IDs.
6. Correct directory/file operation errors.
7. Every invalid filename category, invalid source_id, and non-bytes payload.
8. Input mapping mutation does not alter stored fixtures.
9. Frozen metadata/ref reject mutation.
Run from repository root: python3 -m unittest discover -s tests -v
Use synthetic data only. Keep code clear and small.

## Evidence and honest status
docs/evidence/MODULE-001.md must identify the task, files, Python version, exact test command, real stdout/stderr and exit status, and any limitations.
If your environment cannot run tests, write TESTS_NOT_RUN and the reason. Never manufacture logs or a passing result.
If you cannot inspect the repo or execute code, say so explicitly; you can still deliver source.

## Submission — required
Once done, push the deliverables to https://github.com/Dolesh-avkalan/drive-tool under branch feature/module-001-storage-contract, with commit message "Implement MODULE-001 storage contract and in-memory adapter". Do not push implementation to main.
Only push if your environment actually has authorized GitHub access. Do not request or expose tokens, claim a push you did not perform, or instruct the messenger to implement the module.
If push is unavailable, respond PUSH_BLOCKED and provide every deliverable as a downloadable file or a complete fenced block labeled with its exact repository path. The director will arrange a separate transport step.

## Final response format
MODULE-001
STATUS: DONE | TESTS_NOT_RUN | PUSH_BLOCKED | BLOCKED
BRANCH: feature/module-001-storage-contract
COMMIT: actual SHA or NOT_PUSHED
TESTS: actual command and result, or NOT_RUN
DELIVERABLES: file links or full path-labeled content if not pushed
LIMITATIONS: remaining limitations
Finish only when the output is ready for the director to inspect. Do not start the next module.
