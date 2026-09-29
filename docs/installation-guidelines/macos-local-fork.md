# Run this OpenAlgo fork on a Mac

Repository: https://github.com/jilimudiManvitha/OpenAlgo_MVP

This checkout preserves the local scanner, paper strategy, reports and research
alongside the September 29, 2026 upstream merge. The existing customized files
win wherever both projects changed the same file. Consequently this is a custom
fork, not an unmodified upstream release. In particular the local app startup,
Python dependency lock, scheduler/shutdown customizations and frontend build are
preserved; newly added upstream features needing changes in those files may not
be enabled (including the new OpenScript runner registration/dependency).

## Clone and install

Install Git, Git LFS, uv, and Node.js satisfying `frontend/package.json` (Node 22.22+
is one supported choice). Recreate dependencies on macOS; Windows `.venv` and
`node_modules` cannot be reused.

```sh
git lfs install
git clone https://github.com/jilimudiManvitha/OpenAlgo_MVP.git
cd OpenAlgo_MVP
git lfs pull
git lfs fsck
uv python install 3.12
uv sync --frozen --no-dev --python 3.12
```

The committed frontend build lets the app use the preserved local interface.
To build the merged frontend source instead, install its locked dependencies:

```sh
cd frontend
npm ci
npm run build
cd ..
```

## Restore the saved installation, or start fresh

For existing settings and reports, restore **before starting OpenAlgo**. The
`portable-backup/latest/` directory contains an authenticated encrypted snapshot of
13 files: nine operational/history/report databases, `.env`, the strategy
schedule configuration, and both research candle databases (September 25 and 29). SQLite
files use consistent database backups. The seven encrypted parts and their
manifest must all be present; Git LFS downloads the parts.

Transfer this recovery key separately from Windows, for example to a private
file on the Mac or via a password manager:

`D:\Personal\OpenAlgo_Windows\.migration-private\mac-restore-20260929-latest.key`

The key is deliberately absent from Git. Do not upload it or put it inside the
clone. Use the actual private location in the command below:

```sh
uv run --no-sync python scripts/migration_backup.py restore \
  --root . --backup portable-backup/latest \
  --key-file /path/outside/repository/mac-restore-20260929-latest.key
```

Restore verifies authentication and file hashes and refuses to overwrite
different existing files. Keep the restored APP_KEY, API_KEY_PEPPER and other
encryption settings with the restored databases. Review `.env` and
`strategies/strategy_configs.json` locally for Windows-specific paths, broker
callbacks and schedules; change paths to this Mac's checkout. Sign in to the
broker again. Review scheduled strategies before starting the migrated app.
The backup is a point-in-time snapshot, not continuing synchronization.

For a fresh installation, skip restore, copy `.sample.env` to `.env`, configure
it locally and create a new account. This does not restore old accounts or data.

## Run

```sh
uv run --no-sync app.py
```

Open http://127.0.0.1:5000. Scanner: `/market-scanner`; strategy reports:
`/strategy-reports`. The saved paper strategy runs on India exchange time.

Research reports can be opened without a Windows PowerShell launcher:

```sh
uv run --no-sync python narasimha_pc_backtest/serve.py
```

See each research package's README for extra dependencies and absolute-path
overrides. Mac execution has not been tested on an actual Mac in this session.
Machine caches, virtual environments, test outputs and Git credential-manager
state are regenerated, not transferred. Original Crypto folders outside this
checkout are outside this repository.
