# D102 pins — final candidate

## Candidate (published)
- repo: Dolesh-avkalan/drive-tool
- branch: feature/module-006b-final-service-candidate
- head commit: 337e4c713829af76615472eb47b81244ff399528
- tree: 169855e4541531961cd25bbcba3da8d1109d85c8
- base (parent) commit: ebd05b779cac191ab107d3368e6e1f280a8eac16 (accepted PR9 merge)

## The two added files (unchanged HTTP overlay, byte-identical to source f37a30b)
- drive_tool/http_adapter.py
  - git blob: 41279e6290617968c3b4f3f91fc3cf9a7dab505a
  - sha256:   3ed13cfa7960854382577c9e0982d3ba116833793a6430d141732ccac89c020c
  - bytes:    40881
- tests/test_http_adapter.py
  - git blob: 7a7be06d5ef0e25d0ac54e11bc5909cda27500d3
  - sha256:   b678744759bd53c3dc992e215fc7e98cd5df869c381addbaaa2bfb15e2b87dbf
  - bytes:    76436

## Source hash (composite)
- sourcehash (sha256 over concatenated adapter||test bytes, path order):
  b8b44c4c056e1925957445cc9b532c53194920124a469df54e49053a7dcbb71c

## Overlay source
- drive-tool @ f37a30b0073611c05d26f714f2e833d689673a09
  (branch feature/module-006b-http-busy-budget)
- only these two paths were overlaid; every other path equals base ebd05b77 byte-for-byte.

## Preserved accepted fix
- tests/test_partial_scan_review_fixes.py blob c01003e7015915db3dcac15a168ff7aae3d423db
  (the accepted deterministic test-order fix, preserved unchanged in the base)

## Scope vs base (git diff --name-status ebd05b77..HEAD)
A	drive_tool/http_adapter.py
A	tests/test_http_adapter.py
(exactly 2 additions; no other path changed)
