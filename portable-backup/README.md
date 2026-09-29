# Encrypted installation snapshot — September 29, 2026

Use **`latest/`** for the current migration: seven AES-GCM parts plus its
encrypted manifest contain 13 files, including both September 25 and September
29 research candle databases. All 13 passed decrypt-and-hash verification.
Its separate recovery key is
`D:\Personal\OpenAlgo_Windows\.migration-private\mac-restore-20260929-latest.key`.
Restore commands are in the linked Mac guide below. The root-level snapshot
described next is retained as the earlier point-in-time backup.

Seven authenticated encrypted parts and `manifest.json` contain the databases,
environment settings and saved strategy schedule needed to restore this local
installation. All 12 archived files have passed decrypt-and-hash verification.
Download every part with `git lfs pull`.

The recovery key stays outside Git at
`D:\Personal\OpenAlgo_Windows\.migration-private\mac-restore-20260929.key`.
Transfer it separately and retain a secure copy; losing it makes the snapshot
unrecoverable. Never commit the key.

Follow [the Mac setup and restore guide](../docs/installation-guidelines/macos-local-fork.md).
