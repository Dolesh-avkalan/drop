# D097 evidence manifest

generated: 2026-10-16T02:07:41Z

candidate branch feature/module-006b-http-busy-budget head f37a30b0073611c05d26f714f2e833d689673a09
base b962a04df1c5abdb78c37617d3a6adca02d04024 (adapter blob a28970e2, test blob 8130d56f)
accepted reference b7f8d17b9dcc4aec68d54b38f994290e05264e67
candidate adapter blob 41279e6290617968c3b4f3f91fc3cf9a7dab505a sha256 3ed13cfa7960854382577c9e0982d3ba116833793a6430d141732ccac89c020c
candidate test blob 7a7be06d5ef0e25d0ac54e11bc5909cda27500d3 sha256 b678744759bd53c3dc992e215fc7e98cd5df869c381addbaaa2bfb15e2b87dbf
env: Linux 4.19.0-gvisor x86_64, nproc 2, python3.11.2 / python3.12.13

Verified INPUT harnesses (not re-published here; already in drop):
  d096-http-gate-harness/scripts/http_gate.py           sha256 36770171d78b2541f5b869d3f1c8ef5573eb61eba55ef26c00cc4b1e629954ed
  d095-busy-patch-verification/scripts/http_gate_r1.py  sha256 4bb7a02a27db2fe54e6e1232ee7e136ea79bf497a8be96d04f66d981875ba8f2

Per-call `records`/`cycles` arrays in the JSON logs are omitted for size; the
accounting buckets, resources, schedule fingerprint and problems are retained.
The two saturation JSONs are published in a compact form; their sha256 below is
that of the published bytes. Every file here was verified byte-for-byte against
the pushed blobs (git blob sha).

| file | bytes | sha256 |
| --- | --- | --- |
| `frozen_schedule_manifest.json` | 1309 | `e08fc4fea3115e6636d53acf6d293c7a930dfc724f5992679829a921f4f3d9f7` |
| `logs/d097_gate_3.12.json` | 3980 | `689e453af9fdb658658941360a6151f64d79f56100cbd63ad752c3c8d18556a6` |
| `logs/d097_saturation_3.11.json` | 12573 | `5cf6c34bfb723ccb59a11ad3eada5a8db00e35519121f9b8f55d6bed8a5bc2e4` |
| `logs/d097_saturation_3.12.json` | 12573 | `ba7eb4546bf642cc25738f533adf6a82a1efc1b7520055421ea04dec59c7768a` |
| `logs/d097_smoke_3.11.json` | 1780 | `2fd35c7907629dc458078234e65a51a127947ff379ea923692c69e754b41f222` |
| `logs/full_base_3.11.txt` | 995 | `c4fc54b5938a1b9e2c1d2ba84d2c41a701f0619da4e42628f9011c6dcd2cf27b` |
| `logs/full_base_3.12.txt` | 995 | `1115115ecc3045be861a53481d12b54479fef40aa9bb6874262db3d799df6f11` |
| `logs/full_candidate_3.11.txt` | 1010 | `2ce15ffd334b37faff920452b58e7c2a4150ce816ed93a21eacb30245bf39e11` |
| `logs/full_candidate_3.12.txt` | 1010 | `ebb84afa1d66ff256bca18e43ecb678843f183a7f0ea1493b72fee50ec41d14b` |
| `logs/mutation_battery.txt` | 1758 | `d42fcb6268620cc31d634fc04aaa2bcbf4cf5e84395b92291f5f2f767241e0c4` |
| `logs/probes_all.txt` | 2564 | `1f4750c23ecc95b17613fa2cd906df3fde9474f4468281070dddba70ffe76d31` |
| `logs/r1_saturation_flake_3.12.txt` | 1681 | `5367055bf90d6438bbb7267bbe436b215da51887db793fc58762ee77766ae590` |
| `logs/semantic_revert_guard.txt` | 840 | `39a668798380bbc23226f0ae92dcd837dbd9fddd9a4b51584b3e0f17ae808f9c` |
| `logs/smoke600_3.11.json` | 1821 | `c90e5cd238534053675b8f991ae3c0c54acc77f2c64b185bcc06399ce68e7b6b` |
| `logs/smoke600_3.12.json` | 1818 | `bf5dccd5e393beecdb6dc4532bef558f6bed7980263494f525fc8575e69cfecf` |
| `logs/soak10000_3.11.json` | 1847 | `4897ffbc9e0e8d6b6b4843ad0e3c3b5506b6b589d58670590d7fc34fac8ed80f` |
| `logs/soak10000_3.12.json` | 1847 | `a05593a808f84b38ed5e7fcbef41bb143cfe036f51818222e863d00573fd3efd` |
| `scripts/build_d097_harness.py` | 8686 | `a1f76ae1707b8b0c5a0c4585e7072efa74d1fe847c470642de703234f4f54ffa` |
| `scripts/http_gate_d097.py` | 41887 | `0ecf875e10d6b27dffc42eb379d6fa0ab850fc41018af9f2b8860ac5ffa81d24` |
| `scripts/mutation_battery.py` | 5848 | `d66a8c68dfb1688735d14f83c1c0a80c4638e703e999e4797fb10db625556b8b` |
| `scripts/probe_http_d097.py` | 9270 | `25ca281acd7e1af0b947386e61a7ed416f841e083571de845123a593274614fa` |
