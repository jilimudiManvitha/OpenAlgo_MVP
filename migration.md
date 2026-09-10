# New laptop migration: OpenAlgo Indian Markets MVP

Migration date: 10 September 2026.

## The only repository to use from now on

**Private repository:** https://github.com/Narasimha722/openalo_indian_markets_mvp

The original project is `D:\Personal\openalgo`. Its `origin` now points to this private repository for both fetch and push. The old `fork` remote was removed, and `main` tracks `origin/main`. The old `marketcalls/openalgo` and `Narasimha722/openalgo_opensource` repositories are no longer configured as Git remotes.

This migration preserves the existing `main` commit history and the current application, including the Fyers volume-shocker/top-gainer/top-loser backend, custom skills and skill mirrors, trading code, documentation, personal notes, backtests, and backtest reports. Existing tracked frontend build files are retained. Historical attribution, upstream issue links, and third-party dependency references in old documentation remain historical references, not additional Git remotes.

`autoresearch` is included as ordinary files at its existing revision `228791fb499afffb54b46200aca536f79142f117`. A new clone does not need a separate submodule checkout. Its nested Git metadata was preserved locally under `.migration-private/autoresearch-git` during conversion; that metadata is not needed to use the included files. Project skill junctions are represented by their tracked files in Git, so a new clone gets normal directories and does not depend on junctions pointing at the old laptop.

## Code and data travel separately

Cloning downloads the project and its Git history. Large databases and sensitive local settings are stored in an **encrypted migration backup attached to this same private repository's release**, rather than as plaintext Git files.

- Release tag: `laptop-migration-20260910`.
- Release page: https://github.com/Narasimha722/openalo_indian_markets_mvp/releases/tag/laptop-migration-20260910
- Backup files: `manifest.json` plus every `data-*.enc` part attached to that release.
- Recovery key on the old laptop: `D:\Personal\openalgo\.migration-private\recovery-20260910.key`.
- Local encrypted backup directory: `D:\Personal\openalgo\.migration-private\backup-20260910`.

**Save the recovery key separately before retiring the old laptop.** Copy it to a password manager or an external drive. It is deliberately not committed or uploaded with the backup. Without that key, the encrypted data cannot be restored. Do not put the key into the Git repository or its release attachments.

The backup includes the approximately 31 GB `db/historify.duckdb`, the application/account/settings database, sandbox database, scanner baseline cache, operational SQLite databases, `.env`, and the other selected local configuration/log/result files listed in the backup's encrypted manifest. SQLite files are copied through SQLite's backup API. The Historify file is held under a read-only DuckDB connection during backup; an active cross-process writer or outstanding WAL causes the backup to refuse rather than silently copy an inconsistent file.

The parts use AES-256-GCM encryption with an independently authenticated encrypted manifest. Restore verifies encrypted-part hashes, authentication tags, the compressed archive hash, file inventory, and every restored file's SHA-256. The key itself is never printed by the backup utility.

The migration snapshot contains **15 files**, totaling **33,211,639,221 bytes** before compression. Its **24 encrypted parts plus one manifest** total **12,740,505,228 bytes (11.87 GiB)**:

```text
.cloudflared/config.yml
.env
.vscode/settings.json
db/health.db
db/historify.duckdb
db/latency.db
db/logs.db
db/market_scanner.db
db/openalgo.db
db/sandbox.db
log/errors.jsonl
log/ws_proxy_stats.json
tmp/market-scanner-today-smoke.json
tmp/market-scanner-today.json
tmp/pr1999-context.md
```

SQLite snapshots can have different physical sizes from the source database files while preserving their database contents. The Cloudflare configuration also exists in the code checkout; restore skips it if it is identical to the backed-up copy.

## 1. Prepare the new Windows laptop

Install these tools:

- Git for Windows, including Git Credential Manager.
- `uv` for the project Python environment.
- Node.js 22.22 or newer within the supported Node 22 line (or another version allowed by `frontend/package.json`).
- GitHub CLI (`gh`) to download private release attachments.

Use a 64-bit system. Keep enough free disk space for the restored approximately 31 GB history database, downloaded encrypted parts, a temporary decrypted compressed archive during restore, and dependencies. At least 100 GB of free space is a practical starting point for this migration.

Authenticate with the GitHub account that can access the private repository:

```powershell
gh auth login
gh auth setup-git
```

## 2. Clone the new repository

Keeping the original folder path minimizes changes to personal scripts that contain absolute paths:

```powershell
New-Item -ItemType Directory -Force D:\Personal
git clone https://github.com/Narasimha722/openalo_indian_markets_mvp.git D:\Personal\openalgo
Set-Location D:\Personal\openalgo
git remote -v
git status
```

`git remote -v` should list only `origin`, with the new repository URL for fetch and push. Do not add the former repositories as remotes. If the new laptop has no D: drive, choose an existing drive and update absolute paths in `.env` and personal scripts accordingly.

## 3. Rebuild dependencies

The existing project requires Python 3.12 or newer. Python 3.12 is a suitable consistent starting version for this installation:

```powershell
uv python install 3.12
uv sync --frozen --no-dev --python 3.12
Set-Location frontend
npm ci
npm run build
Set-Location ..
```

The checked-in frontend build is retained, but rebuilding ensures it matches your environment. Virtual environments and `node_modules` are recreated rather than copied from the old Windows installation.

Personal backtesting scripts can have additional dependencies documented in `backtesting/stratagies/nifty50_research_requirements.txt` and `backtesting/ha_bb_vwap_reports/requirements.txt`. Their former `backtesting/.venv` is not portable and is not included. The optional `autoresearch` experiment has its own `pyproject.toml` and environment requirements; it is not required to run OpenAlgo.

## 4. Download and restore the encrypted data

**Do this before starting the application for the first time.** Starting first can create a new `.env` and databases. The restore utility refuses to overwrite different existing files; it can skip existing identical files safely.

```powershell
New-Item -ItemType Directory -Force D:\Backups\openalgo-20260910
gh release download laptop-migration-20260910 --repo Narasimha722/openalo_indian_markets_mvp --dir D:\Backups\openalgo-20260910

# Replace E:\ with the actual location where you saved the recovery key.
uv run --no-sync python scripts/migration_backup.py restore --root D:\Personal\openalgo --backup D:\Backups\openalgo-20260910 --key-file E:\recovery-20260910.key
```

Download **all** encrypted parts and `manifest.json`. Individual parts are not usable by themselves. A missing or modified part, or the wrong key, is rejected before any settings/data are restored. Do not extract into an already-running OpenAlgo installation.

To verify a downloaded backup without restoring its files, use `verify` instead of `restore` and point `--root` to a scratch directory with sufficient free space. The scratch directory is used for the temporary decrypted archive and is cleaned up after verification.

## 5. Check local settings before startup

Open the restored `.env` locally. Keep the original `APP_KEY`, `API_KEY_PEPPER`, and `FERNET_SALT` with the original databases; replacing them can break session validation, API-key/password checks, or encrypted broker-token access. Do not overwrite the restored `.env` with `.sample.env`.

Check database paths, any Historify path override, browser executable paths, local host/port settings, and broker callback URLs against the new machine. If a broker application restricts access by IP address, update its configured allowed IP for the new connection where applicable. Sign in to Fyers again after migration; saved broker access tokens can expire.

The standard `.env` contains relative SQLite paths that work from the repository root. Run commands from `D:\Personal\openalgo` unless you deliberately update those paths.

If you intentionally want a fresh installation without the backed-up account/settings/data, copy `.sample.env` to `.env`, configure it, and create a new account through the application instead of restoring the backup. That does not recover old watchlists, settings, or historical data.

## 6. Start and check the application

```powershell
uv run app.py
```

Open the local address printed by the server, sign in with your existing OpenAlgo account, and log in to Fyers. Check your watchlists, saved settings, Historify coverage, and strategies. Review strategies before deliberately enabling automated execution on the new machine.

The volume-shocker and daily movers backend is included. Its UI is still deferred. In a second terminal:

```powershell
Set-Location D:\Personal\openalgo
uv run scripts/market_scanner.py --symbols ATHERENERG RELIANCE SBIN --limit 10
```

Full usage: [Fyers scanner documentation](docs/api/market-scanner.md).

## 7. Future updates and pushes

Use only the new repository:

```powershell
git pull --ff-only origin main

# After making changes:
git add --all
git commit -m "Describe the change"
git push origin main
```

`.env`, databases, encryption keys and `.migration-private/` remain outside Git. The release backup is a point-in-time migration snapshot, not an ongoing database synchronization service. If important data changes later, create a new encrypted backup and retain its recovery key separately.

Do not use legacy public-repository one-line installers or prebuilt public Docker images for this private application snapshot. Clone this repository and build locally using the steps above. Historical installation documents elsewhere in the repository may still describe the original public project.

## What is not pushed as ordinary Git files

| Item | Migration treatment |
| --- | --- |
| `.env` and selected local settings | Encrypted release backup; never plaintext Git |
| `db/historify.duckdb` and operational `db/*.db` | Encrypted release backup |
| Selected runtime logs and temporary scan outputs | Encrypted release backup |
| Recovery key and `.migration-private/` working files | Local only; save the key separately |
| `.venv/`, `backtesting/.venv/`, `node_modules/`, Python bytecode, test/lint caches and package metadata | Regenerate on the new laptop |
| Untracked generated `frontend/dist/` assets and compressed `.gz`/`.br` variants | Regenerate with the frontend build and application startup; already tracked build files remain in Git |
| Test databases and SQLite WAL/SHM sidecars | Excluded; operational SQLite state is captured by the consistent database snapshots |
| Original `.git` directory, remote-tracking caches and hooks | A clone creates fresh Git metadata; `main` history is pushed normally |
| `.worktrees/` and preserved nested `autoresearch` Git metadata | Local working metadata, not required for the migrated current files |
| Files outside `D:\Personal\openalgo` | Outside the requested folder and not uploaded |

In particular, the separate `D:\Personal\historify_ATHERENERG_20260908_112029` CSV directory and the separate `D:\Personal\openalgo_Crypto` clone are outside this migration's requested folder. Copy them separately if needed. CSVs and reports already present inside the personal backtesting folder are included in Git.

## Verification record

The destination was verified private and empty before migration. The existing Git history was checked for blobs over GitHub's 100 MiB ordinary-file limit; none were found.

- Source migration commit: `31a555cbd`; additional skill references and inventory: `9669501b3`. Both were pushed to the new `origin/main`.
- All 64 pre-existing local tags were pushed. The migration release adds its own separate tag.
- A fresh full clone from the new private repository succeeded, preserved the main history, and was updated to `9669501b3`. It contains 4,778 tracked files, uses only the new `origin`, and has normal skill directories instead of old-machine junctions.
- All five migration backup tests passed: exact round-trip, verify-only, damaged-file rejection, wrong-key rejection, and refusal to overwrite different files. Ruff lint/format checks passed for the backup utility and tests.
- Full local verification of the real migration backup succeeded: all 24 encrypted parts authenticated, and all 15 archived files matched their recorded sizes and SHA-256 hashes.
- Release upload and remote asset verification are in progress. The release remains a draft until every uploaded asset is verified; publication will be recorded here when complete.

Storage references: [GitHub ordinary-file limits](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github) and [GitHub release asset limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases). Each encrypted part is approximately 512 MiB, below the 2 GiB release-asset limit.
