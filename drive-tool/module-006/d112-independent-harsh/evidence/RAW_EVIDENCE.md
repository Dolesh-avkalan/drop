# d110 harsh extension — raw sandbox evidence

This file is generated from the raw per-stage stdout captured by `run_harsh_target.py` during local sandbox validation against the pinned candidate. It is NOT a target result.

Sandbox: Debian 12 x86_64, sandbox `/tmp` = 9p, floor overridden to 32 MiB via `--min-free-bytes` for validation only.


## py312 — summary (result=PASS, exit=0)

```json
{
  "result": "PASS",
  "exit": 0,
  "hostname": "claw-sandbox-65a1a6a5cb1bd29d9ef09aa6b0",
  "archive_sha256": "191d6f2bd985be51f1b6092472beeec25b267a4c6e89de7817b4d6538c61c6c3",
  "payload_sha256": "b94eb09ad329abe669633834fe21b67139b43c0fe666645cde263e2139f53e0e",
  "identity": {
    "checked": 28,
    "problems": []
  },
  "payload": {
    "path": "harsh_gate_d110.py",
    "problems": [],
    "sha256": "b94eb09ad329abe669633834fe21b67139b43c0fe666645cde263e2139f53e0e"
  },
  "resources": {
    "elapsed_seconds": 19.509,
    "free_bytes": 64479232,
    "within_workspace_bound": true,
    "workspace_allocated_bytes": 2333696,
    "workspace_limit_bytes": 201326592
  },
  "manifest": {
    "files": 132,
    "path": "source_manifest.tsv"
  }
}
```

### py312 — per-stage raw stdout


#### py312 / selfcheck

```json
{
  "capabilities": {
    "free_bytes": 64552960,
    "free_floor_bytes": 33554432,
    "mem_available_kb": 2065116,
    "oom_score_adj_writable": true,
    "os_link_supported": true,
    "platform": "linux",
    "python": "3.12.13 (main, May  8 2026, 20:08:05) [GCC 12.2.0]",
    "rlimit_as_settable": true,
    "rlimit_fsize_settable": true,
    "rlimit_nofile_settable": true,
    "sigxfsz_ignorable": true,
    "tmp_fstype": "9p"
  },
  "problems": [],
  "result": "PASS",
  "stage": "selfcheck"
}
```

#### py312 / readdir_order

```json
{
  "inverted_run": {
    "ok": true,
    "rc": 0,
    "tail": [
      "Ran 1 test in 0.000s",
      "",
      "OK (skipped=1)"
    ]
  },
  "native_readdir_order": [
    "b.txt",
    "a.txt"
  ],
  "native_run": {
    "ok": true,
    "rc": 0,
    "tail": [
      "Ran 1 test in 0.007s",
      "",
      "OK"
    ]
  },
  "note": "The committed test is order-explicit (it injects both ['a.txt','b.txt'] and ['b.txt','a.txt']); the accepted fix must pass under either host readdir order.",
  "problems": [],
  "result": "PASS",
  "stage": "readdir_order",
  "test_id": "tests.test_partial_scan_review_fixes.PostYieldStorageErrorTests.test_metadata_failure_below_root_is_skipped_and_charged",
  "tmp_fstype": "9p"
}
```

#### py312 / http_hostile

```json
{
  "cases": {
    "bad_method": {
      "bytes": 183,
      "code": "invalid",
      "status": 400
    },
    "bare_lf_header_block": {
      "bytes": 183,
      "code": "invalid",
      "status": 400
    },
    "buffered_trailing_bytes": {
      "bytes": 183,
      "code": "invalid",
      "status": 400
    },
    "duplicate_content_length": {
      "bytes": 183,
      "code": "invalid",
      "status": 400
    },
    "huge_digit_content_length": {
      "bytes": 191,
      "code": "too_large",
      "status": 413
    },
    "non_digit_content_length": {
      "bytes": 183,
      "code": "invalid",
      "status": 400
    },
    "overlong_header_block": {
      "bytes": 183,
      "code": "invalid",
      "status": 400
    },
    "overlong_request_line": {
      "bytes": 183,
      "code": "invalid",
      "status": 400
    },
    "oversize_json_body": {
      "bytes": 191,
      "code": "too_large",
      "status": 413
    },
    "oversize_save_body": {
      "bytes": 191,
      "code": "too_large",
      "status": 413
    },
    "post_hostile_recovery": {
      "bytes": 628,
      "code": null,
      "status": 200
    },
    "slow_partial_body": {
      "bytes": 186,
      "code": "timeout",
      "status": 504
    },
    "too_many_headers": {
      "bytes": 183,
      "code": "invalid",
      "status": 400
    },
    "unknown_endpoint": {
      "bytes": 183,
      "code": "invalid",
      "status": 400
    }
  },
  "problems": [],
  "resources": {
    "closed": true,
    "fd_after": 4,
    "fd_before": 10,
    "threads_after": []
  },
  "result": "PASS",
  "stage": "http_hostile"
}
```

#### py312 / admission

```json
{
  "cycles": [
    {
      "cycle": 0,
      "entered": true,
      "excess": [
        503,
        "busy"
      ],
      "occupiers_bad": 0,
      "occupiers_ok": 6
    },
    {
      "cycle": 1,
      "entered": true,
      "excess": [
        503,
        "busy"
      ],
      "occupiers_bad": 0,
      "occupiers_ok": 6
    },
    {
      "cycle": 2,
      "entered": true,
      "excess": [
        503,
        "busy"
      ],
      "occupiers_bad": 0,
      "occupiers_ok": 6
    },
    {
      "cycle": 3,
      "entered": true,
      "excess": [
        503,
        "busy"
      ],
      "occupiers_bad": 0,
      "occupiers_ok": 6
    },
    {
      "cycle": 4,
      "entered": true,
      "excess": [
        503,
        "busy"
      ],
      "occupiers_bad": 0,
      "occupiers_ok": 6
    },
    {
      "cycle": 5,
      "entered": true,
      "excess": [
        503,
        "busy"
      ],
      "occupiers_bad": 0,
      "occupiers_ok": 6
    },
    {
      "cycle": 6,
      "entered": true,
      "excess": [
        503,
        "busy"
      ],
      "occupiers_bad": 0,
      "occupiers_ok": 6
    },
    {
      "cycle": 7,
      "entered": true,
      "excess": [
        503,
        "busy"
      ],
      "occupiers_bad": 0,
      "occupiers_ok": 6
    }
  ],
  "frozen": {
    "cycles": 8,
    "excess": 1,
    "occupiers": 6
  },
  "problems": [],
  "recovery": {
    "code": null,
    "status": 200
  },
  "resources": {
    "closed": true,
    "fd_after": 4,
    "fd_before": 10
  },
  "result": "PASS",
  "stage": "admission"
}
```

#### py312 / isolation

```json
{
  "checks": {
    "cross_agent_other": {
      "error": {
        "code": "denied",
        "outcome_uncertain": false,
        "retry_safe": false
      },
      "ok": false
    },
    "cross_agent_other_read": {
      "error": {
        "code": "denied",
        "outcome_uncertain": false,
        "retry_safe": false
      },
      "ok": false
    },
    "ro_save_denied": {
      "error": {
        "code": "denied",
        "outcome_uncertain": false,
        "retry_safe": false
      },
      "ok": false
    },
    "shared_alias_a": {
      "ok": true,
      "value": {
        "items": [
          {
            "kind": "file",
            "name": "data.bin",
            "parent_id": "root",
            "ref": {
              "file_id": "p/data.bin",
              "source_id": "shared"
            },
            "size_bytes": 4096
          },
          {
            "kind": "file",
            "name": "readme.txt",
            "parent_id": "root",
            "ref": {
              "file_id": "p/readme.txt",
              "source_id": "shared"
            },
            "size_bytes": 80
          },
          {
            "kind": "directory",
            "name": "savepool",
            "parent_id": "root",
            "ref": {
              "file_id": "p/savepool",
              "source_id": "shared"
            },
            "size_bytes": null
          },
          {
            "kind": "directory",
            "name": "sub",
            "parent_id": "root",
            "ref": {
              "file_id": "p/sub",
              "source_id": "shared"
            },
            "size_bytes": null
          }
        ],
        "next_offset": null
      }
    },
    "shared_alias_b": {
      "ok": true,
      "value": {
        "items": [
          {
            "kind": "file",
            "name": "data.bin",
            "parent_id": "root",
            "ref": {
              "file_id": "p/data.bin",
              "source_id": "shared"
            },
            "size_bytes": 4096
          },
          {
            "kind": "file",
            "name": "readme.txt",
            "parent_id": "root",
            "ref": {
              "file_id": "p/readme.txt",
              "source_id": "shared"
            },
            "size_bytes": 80
          },
          {
            "kind": "directory",
            "name": "savepool",
            "parent_id": "root",
            "ref": {
              "file_id": "p/savepool",
              "source_id": "shared"
            },
            "size_bytes": null
          },
          {
            "kind": "directory",
            "name": "sub",
            "parent_id": "root",
            "ref": {
              "file_id": "p/sub",
              "source_id": "shared"
            },
            "size_bytes": null
          }
        ],
        "next_offset": null
      }
    },
    "symlink_list": {
      "error": {
        "code": "denied",
        "outcome_uncertain": false,
        "retry_safe": false
      },
      "ok": false
    },
    "symlink_read": {
      "error": {
        "code": "denied",
        "outcome_uncertain": false,
        "retry_safe": false
      },
      "ok": false
    },
    "symlink_save": {
      "error": {
        "code": "denied",
        "outcome_uncertain": true,
        "retry_safe": false
      },
      "ok": false
    },
    "traversal_dotdot": {
      "client_reject": "ValueError",
      "ok": false
    },
    "traversal_encoded": {
      "error": {
        "code": "not_found",
        "outcome_uncertain": false,
        "retry_safe": false
      },
      "ok": false
    }
  },
  "outside_listing": [
    "secret.txt"
  ],
  "problems": [],
  "result": "PASS",
  "stage": "isolation"
}
```

#### py312 / concurrency

```json
{
  "detail": {
    "create": {
      "exists": 5,
      "other": [],
      "winners": 1
    },
    "create_parents": {
      "errors": []
    },
    "overwrite": {
      "busy_reads": 0,
      "errors": [],
      "torn_count": 0,
      "torn_reads": []
    },
    "temp_leaks": {}
  },
  "problems": [],
  "result": "PASS",
  "stage": "concurrency"
}
```

#### py312 / crash_kill

```json
{
  "cases": {
    "midwrite": {
      "killed_by_sigkill": true,
      "mode": "mid_write",
      "orphan_temps": 1,
      "published": false,
      "ready": true,
      "recovery": {
        "find_ok": true,
        "list_ok": true,
        "on_disk_temps": 1,
        "read_ok": true,
        "save_ok": true,
        "temp_in_find": false,
        "temp_in_list": false
      }
    },
    "orphan_visibility": {
      "on_disk_temps": 1,
      "temp_in_find": false,
      "temp_in_list": false
    },
    "prepublish": {
      "killed_by_sigkill": true,
      "mode": "pre_publish",
      "orphan_temps": 1,
      "published": false,
      "ready": true,
      "recovery": {
        "find_ok": true,
        "list_ok": true,
        "on_disk_temps": 1,
        "read_ok": true,
        "save_ok": true,
        "temp_in_find": false,
        "temp_in_list": false
      }
    },
    "storm": {
      "errors": [],
      "killed": 4,
      "recovery_ok": true,
      "torn": 0
    }
  },
  "note": "SIGKILL terminates user space only; this proves process-crash atomicity, NOT physical power-loss durability. No physical-power-loss claim is made.",
  "problems": [],
  "result": "PASS",
  "stage": "crash_kill"
}
```

#### py312 / resource_pressure

```json
{
  "problems": [],
  "result": "PASS",
  "stage": "resource_pressure",
  "sub": {
    "cpu": {
      "calls_ok": 200,
      "errors": []
    },
    "fd": {
      "emfile_forced": true,
      "fillers": 8,
      "mapped_service_errors": 120,
      "nfd_after": 4,
      "nfd_before": 4,
      "nofile_hard": 1073741816,
      "nofile_soft_before": 1073741816,
      "nofile_soft_lowered": 12,
      "recovered": true,
      "unhandled": []
    },
    "ram": {
      "mem_after_kb": 2064008,
      "mem_before_kb": 2024468,
      "result": {
        "as_mib": 384,
        "memoryerror_raised": true,
        "ops": 200,
        "ops_ok": true,
        "post_ok": true,
        "rss_kb": 31848
      }
    }
  }
}
```

#### py312 / enospc

```json
{
  "phases": {
    "fsync": {
      "error": {
        "code": "unavailable",
        "outcome_uncertain": true,
        "retry_safe": false
      },
      "fd_delta": 0,
      "no_partial_new": true,
      "target_preserved": true,
      "temp_leaks": {}
    },
    "mid_write": {
      "error": {
        "code": "unavailable",
        "outcome_uncertain": true,
        "retry_safe": false
      },
      "fd_delta": 0,
      "no_partial_new": true,
      "target_preserved": true,
      "temp_leaks": {}
    },
    "publish": {
      "error": {
        "code": "unavailable",
        "outcome_uncertain": true,
        "retry_safe": false
      },
      "fd_delta": 0,
      "no_partial_new": true,
      "target_preserved": true,
      "temp_leaks": {}
    },
    "recovery": {
      "ok": true
    },
    "rlimit_fsize": {
      "code": "unavailable",
      "outcome_uncertain": true,
      "retry_safe": false,
      "target_preserved": true,
      "temp_leaks": 0
    },
    "temp_create": {
      "error": {
        "code": "unavailable",
        "outcome_uncertain": true,
        "retry_safe": false
      },
      "fd_delta": 0,
      "no_partial_new": true,
      "target_preserved": true,
      "temp_leaks": {}
    }
  },
  "problems": [],
  "result": "PASS",
  "stage": "enospc"
}
```

## py311 — summary (result=PASS, exit=0)

```json
{
  "result": "PASS",
  "exit": 0,
  "hostname": "claw-sandbox-65a1a6a5cb1bd29d9ef09aa6b0",
  "archive_sha256": "191d6f2bd985be51f1b6092472beeec25b267a4c6e89de7817b4d6538c61c6c3",
  "payload_sha256": "b94eb09ad329abe669633834fe21b67139b43c0fe666645cde263e2139f53e0e",
  "identity": {
    "checked": 28,
    "problems": []
  },
  "payload": {
    "path": "harsh_gate_d110.py",
    "problems": [],
    "sha256": "b94eb09ad329abe669633834fe21b67139b43c0fe666645cde263e2139f53e0e"
  },
  "resources": {
    "elapsed_seconds": 17.785,
    "free_bytes": 55017472,
    "within_workspace_bound": true,
    "workspace_allocated_bytes": 2333696,
    "workspace_limit_bytes": 201326592
  },
  "manifest": {
    "files": 132,
    "path": "source_manifest.tsv"
  }
}
```

### py311 — per-stage raw stdout


#### py311 / selfcheck

```json
{
  "capabilities": {
    "free_bytes": 55091200,
    "free_floor_bytes": 33554432,
    "mem_available_kb": 2060296,
    "oom_score_adj_writable": true,
    "os_link_supported": true,
    "platform": "linux",
    "python": "3.11.2 (main, May 12 2026, 05:17:27) [GCC 12.2.0]",
    "rlimit_as_settable": true,
    "rlimit_fsize_settable": true,
    "rlimit_nofile_settable": true,
    "sigxfsz_ignorable": true,
    "tmp_fstype": "9p"
  },
  "problems": [],
  "result": "PASS",
  "stage": "selfcheck"
}
```

#### py311 / readdir_order

```json
{
  "inverted_run": {
    "ok": true,
    "rc": 0,
    "tail": [
      "Ran 1 test in 0.000s",
      "",
      "OK (skipped=1)"
    ]
  },
  "native_readdir_order": [
    "b.txt",
    "a.txt"
  ],
  "native_run": {
    "ok": true,
    "rc": 0,
    "tail": [
      "Ran 1 test in 0.006s",
      "",
      "OK"
    ]
  },
  "note": "The committed test is order-explicit (it injects both ['a.txt','b.txt'] and ['b.txt','a.txt']); the accepted fix must pass under either host readdir order.",
  "problems": [],
  "result": "PASS",
  "stage": "readdir_order",
  "test_id": "tests.test_partial_scan_review_fixes.PostYieldStorageErrorTests.test_metadata_failure_below_root_is_skipped_and_charged",
  "tmp_fstype": "9p"
}
```

#### py311 / http_hostile

```json
{
  "cases": {
    "bad_method": {
      "bytes": 183,
      "code": "invalid",
      "status": 400
    },
    "bare_lf_header_block": {
      "bytes": 183,
      "code": "invalid",
      "status": 400
    },
    "buffered_trailing_bytes": {
      "bytes": 183,
      "code": "invalid",
      "status": 400
    },
    "duplicate_content_length": {
      "bytes": 183,
      "code": "invalid",
      "status": 400
    },
    "huge_digit_content_length": {
      "bytes": 191,
      "code": "too_large",
      "status": 413
    },
    "non_digit_content_length": {
      "bytes": 183,
      "code": "invalid",
      "status": 400
    },
    "overlong_header_block": {
      "bytes": 183,
      "code": "invalid",
      "status": 400
    },
    "overlong_request_line": {
      "bytes": 183,
      "code": "invalid",
      "status": 400
    },
    "oversize_json_body": {
      "bytes": 191,
      "code": "too_large",
      "status": 413
    },
    "oversize_save_body": {
      "bytes": 191,
      "code": "too_large",
      "status": 413
    },
    "post_hostile_recovery": {
      "bytes": 628,
      "code": null,
      "status": 200
    },
    "slow_partial_body": {
      "bytes": 186,
      "code": "timeout",
      "status": 504
    },
    "too_many_headers": {
      "bytes": 183,
      "code": "invalid",
      "status": 400
    },
    "unknown_endpoint": {
      "bytes": 183,
      "code": "invalid",
      "status": 400
    }
  },
  "problems": [],
  "resources": {
    "closed": true,
    "fd_after": 4,
    "fd_before": 10,
    "threads_after": []
  },
  "result": "PASS",
  "stage": "http_hostile"
}
```

#### py311 / admission

```json
{
  "cycles": [
    {
      "cycle": 0,
      "entered": true,
      "excess": [
        503,
        "busy"
      ],
      "occupiers_bad": 0,
      "occupiers_ok": 6
    },
    {
      "cycle": 1,
      "entered": true,
      "excess": [
        503,
        "busy"
      ],
      "occupiers_bad": 0,
      "occupiers_ok": 6
    },
    {
      "cycle": 2,
      "entered": true,
      "excess": [
        503,
        "busy"
      ],
      "occupiers_bad": 0,
      "occupiers_ok": 6
    },
    {
      "cycle": 3,
      "entered": true,
      "excess": [
        503,
        "busy"
      ],
      "occupiers_bad": 0,
      "occupiers_ok": 6
    },
    {
      "cycle": 4,
      "entered": true,
      "excess": [
        503,
        "busy"
      ],
      "occupiers_bad": 0,
      "occupiers_ok": 6
    },
    {
      "cycle": 5,
      "entered": true,
      "excess": [
        503,
        "busy"
      ],
      "occupiers_bad": 0,
      "occupiers_ok": 6
    },
    {
      "cycle": 6,
      "entered": true,
      "excess": [
        503,
        "busy"
      ],
      "occupiers_bad": 0,
      "occupiers_ok": 6
    },
    {
      "cycle": 7,
      "entered": true,
      "excess": [
        503,
        "busy"
      ],
      "occupiers_bad": 0,
      "occupiers_ok": 6
    }
  ],
  "frozen": {
    "cycles": 8,
    "excess": 1,
    "occupiers": 6
  },
  "problems": [],
  "recovery": {
    "code": null,
    "status": 200
  },
  "resources": {
    "closed": true,
    "fd_after": 4,
    "fd_before": 10
  },
  "result": "PASS",
  "stage": "admission"
}
```

#### py311 / isolation

```json
{
  "checks": {
    "cross_agent_other": {
      "error": {
        "code": "denied",
        "outcome_uncertain": false,
        "retry_safe": false
      },
      "ok": false
    },
    "cross_agent_other_read": {
      "error": {
        "code": "denied",
        "outcome_uncertain": false,
        "retry_safe": false
      },
      "ok": false
    },
    "ro_save_denied": {
      "error": {
        "code": "denied",
        "outcome_uncertain": false,
        "retry_safe": false
      },
      "ok": false
    },
    "shared_alias_a": {
      "ok": true,
      "value": {
        "items": [
          {
            "kind": "file",
            "name": "data.bin",
            "parent_id": "root",
            "ref": {
              "file_id": "p/data.bin",
              "source_id": "shared"
            },
            "size_bytes": 4096
          },
          {
            "kind": "file",
            "name": "readme.txt",
            "parent_id": "root",
            "ref": {
              "file_id": "p/readme.txt",
              "source_id": "shared"
            },
            "size_bytes": 80
          },
          {
            "kind": "directory",
            "name": "savepool",
            "parent_id": "root",
            "ref": {
              "file_id": "p/savepool",
              "source_id": "shared"
            },
            "size_bytes": null
          },
          {
            "kind": "directory",
            "name": "sub",
            "parent_id": "root",
            "ref": {
              "file_id": "p/sub",
              "source_id": "shared"
            },
            "size_bytes": null
          }
        ],
        "next_offset": null
      }
    },
    "shared_alias_b": {
      "ok": true,
      "value": {
        "items": [
          {
            "kind": "file",
            "name": "data.bin",
            "parent_id": "root",
            "ref": {
              "file_id": "p/data.bin",
              "source_id": "shared"
            },
            "size_bytes": 4096
          },
          {
            "kind": "file",
            "name": "readme.txt",
            "parent_id": "root",
            "ref": {
              "file_id": "p/readme.txt",
              "source_id": "shared"
            },
            "size_bytes": 80
          },
          {
            "kind": "directory",
            "name": "savepool",
            "parent_id": "root",
            "ref": {
              "file_id": "p/savepool",
              "source_id": "shared"
            },
            "size_bytes": null
          },
          {
            "kind": "directory",
            "name": "sub",
            "parent_id": "root",
            "ref": {
              "file_id": "p/sub",
              "source_id": "shared"
            },
            "size_bytes": null
          }
        ],
        "next_offset": null
      }
    },
    "symlink_list": {
      "error": {
        "code": "denied",
        "outcome_uncertain": false,
        "retry_safe": false
      },
      "ok": false
    },
    "symlink_read": {
      "error": {
        "code": "denied",
        "outcome_uncertain": false,
        "retry_safe": false
      },
      "ok": false
    },
    "symlink_save": {
      "error": {
        "code": "denied",
        "outcome_uncertain": true,
        "retry_safe": false
      },
      "ok": false
    },
    "traversal_dotdot": {
      "client_reject": "ValueError",
      "ok": false
    },
    "traversal_encoded": {
      "error": {
        "code": "not_found",
        "outcome_uncertain": false,
        "retry_safe": false
      },
      "ok": false
    }
  },
  "outside_listing": [
    "secret.txt"
  ],
  "problems": [],
  "result": "PASS",
  "stage": "isolation"
}
```

#### py311 / concurrency

```json
{
  "detail": {
    "create": {
      "exists": 5,
      "other": [],
      "winners": 1
    },
    "create_parents": {
      "errors": []
    },
    "overwrite": {
      "busy_reads": 0,
      "errors": [],
      "torn_count": 0,
      "torn_reads": []
    },
    "temp_leaks": {}
  },
  "problems": [],
  "result": "PASS",
  "stage": "concurrency"
}
```

#### py311 / crash_kill

```json
{
  "cases": {
    "midwrite": {
      "killed_by_sigkill": true,
      "mode": "mid_write",
      "orphan_temps": 1,
      "published": false,
      "ready": true,
      "recovery": {
        "find_ok": true,
        "list_ok": true,
        "on_disk_temps": 1,
        "read_ok": true,
        "save_ok": true,
        "temp_in_find": false,
        "temp_in_list": false
      }
    },
    "orphan_visibility": {
      "on_disk_temps": 1,
      "temp_in_find": false,
      "temp_in_list": false
    },
    "prepublish": {
      "killed_by_sigkill": true,
      "mode": "pre_publish",
      "orphan_temps": 1,
      "published": false,
      "ready": true,
      "recovery": {
        "find_ok": true,
        "list_ok": true,
        "on_disk_temps": 1,
        "read_ok": true,
        "save_ok": true,
        "temp_in_find": false,
        "temp_in_list": false
      }
    },
    "storm": {
      "errors": [],
      "killed": 4,
      "recovery_ok": true,
      "torn": 0
    }
  },
  "note": "SIGKILL terminates user space only; this proves process-crash atomicity, NOT physical power-loss durability. No physical-power-loss claim is made.",
  "problems": [],
  "result": "PASS",
  "stage": "crash_kill"
}
```

#### py311 / resource_pressure

```json
{
  "problems": [],
  "result": "PASS",
  "stage": "resource_pressure",
  "sub": {
    "cpu": {
      "calls_ok": 200,
      "errors": []
    },
    "fd": {
      "emfile_forced": true,
      "fillers": 8,
      "mapped_service_errors": 120,
      "nfd_after": 4,
      "nfd_before": 4,
      "nofile_hard": 1073741816,
      "nofile_soft_before": 1073741816,
      "nofile_soft_lowered": 12,
      "recovered": true,
      "unhandled": []
    },
    "ram": {
      "mem_after_kb": 2058712,
      "mem_before_kb": 2016288,
      "result": {
        "as_mib": 384,
        "memoryerror_raised": true,
        "ops": 200,
        "ops_ok": true,
        "post_ok": true,
        "rss_kb": 31664
      }
    }
  }
}
```

#### py311 / enospc

```json
{
  "phases": {
    "fsync": {
      "error": {
        "code": "unavailable",
        "outcome_uncertain": true,
        "retry_safe": false
      },
      "fd_delta": 0,
      "no_partial_new": true,
      "target_preserved": true,
      "temp_leaks": {}
    },
    "mid_write": {
      "error": {
        "code": "unavailable",
        "outcome_uncertain": true,
        "retry_safe": false
      },
      "fd_delta": 0,
      "no_partial_new": true,
      "target_preserved": true,
      "temp_leaks": {}
    },
    "publish": {
      "error": {
        "code": "unavailable",
        "outcome_uncertain": true,
        "retry_safe": false
      },
      "fd_delta": 0,
      "no_partial_new": true,
      "target_preserved": true,
      "temp_leaks": {}
    },
    "recovery": {
      "ok": true
    },
    "rlimit_fsize": {
      "code": "unavailable",
      "outcome_uncertain": true,
      "retry_safe": false,
      "target_preserved": true,
      "temp_leaks": 0
    },
    "temp_create": {
      "error": {
        "code": "unavailable",
        "outcome_uncertain": true,
        "retry_safe": false
      },
      "fd_delta": 0,
      "no_partial_new": true,
      "target_preserved": true,
      "temp_leaks": {}
    }
  },
  "problems": [],
  "result": "PASS",
  "stage": "enospc"
}
```

## Guard negatives (fail-closed)

```text
NEG1 tampered payload -> exit 1
  payload sha256 mismatch: 6a4af56a... != b94eb09a...
NEG2 tampered archive -> exit 1
  archive sha256 af58772a... != pin 191d6f2b...
NEG3 content tamper of drive_tool/http_adapter.py -> flagged:
  size mismatch drive_tool/http_adapter.py: 40893 != 40881
  blob mismatch drive_tool/http_adapter.py: 1b1cd1a9... != 41279e62...
  sha256 mismatch drive_tool/http_adapter.py: 97cd7726... != 3ed13cfa...
  unexpected importable file: tests/__pycache__/test_http_adapter.cpython-312.pyc
```