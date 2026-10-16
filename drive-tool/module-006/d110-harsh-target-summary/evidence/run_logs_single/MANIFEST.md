# D110 harsh-fault run manifest

- runner: d110-harsh-fault-runner
- mode: sandbox
- host: claw-sandbox-404a053f93c6ba244db114eefa (verified=False)
- pin: Dolesh-avkalan/drive-tool @ 337e4c713829af76615472eb47b81244ff399528
- payload sha256: 5599d32fa9df7918a8809098492284cebbce42b9141c61844c18c069fc17db43
- workspace: /scratch/work/d110/ws/d110-337e4c71-605-744389
- archive sha256: 191d6f2bd985be51f1b6092472beeec25b267a4c6e89de7817b4d6538c61c6c3
- result: PARTIAL (exit 1)

## Stages

| interpreter | stage | result | raw exit | timed out |
| --- | --- | --- | --- | --- |
| /usr/local/bin/python3 | selfcheck | PASS | 0 | False |
| /usr/local/bin/python3 | http_hostile | PASS | 0 | False |
| /usr/local/bin/python3 | admission_exhaustion | PASS | 0 | False |
| /usr/local/bin/python3 | isolation | PASS | 0 | False |
| /usr/local/bin/python3 | concurrent_ops | PASS | 0 | False |
| /usr/local/bin/python3 | crash_kill | PASS | 0 | False |
| /usr/local/bin/python3 | resource_pressure | PARTIAL | 2 | False |
| /usr/local/bin/python3 | enospc | PASS | 0 | False |

