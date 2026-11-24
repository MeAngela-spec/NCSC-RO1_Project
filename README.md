# NCSC-RO1_Project
Document Routing and Tracking System

Python document routing and tracking for NCSC Regional Office I. The starting
source is the `NCSC_RO1.zip` supplied on 24 November 2026. Existing document
flows, NCSC assets, routing-slip template and sample files are retained.

## Current application

- Individual staff logins, department access and account management.
- Adaptive Excel / CSV and document imports, including saved email intake.
- Document viewing, editing, routing, requested actions, status and MOV files.
- Excel / Word / PDF reports, readable print matrices and original-template slips.
- Selected deletion, restoration and administrator-only permanent deletion.
- SQLite database and supporting files stored together in a local `data` folder.

The current interface opens in a browser served by Python on the host computer.
It works without internet for local records and files. Internet links require
their own service access. Several departments sharing one workspace need a
reachable office LAN and an awake host; installing separate database copies
does not automatically synchronize them.

## Installer work

The target is a Windows installer bundling Python and application dependencies,
so office users will not install Python or run pip themselves. The repository
currently contains the application source; an installer has not been built or
published yet. Host/client setup and desktop packaging are the next stage.

Exact-template PDF conversion currently uses Microsoft Word or LibreOffice on
the host. The Windows packaging stage must address this dependency as well.
Print matrix itself works without that converter.

## Developer setup on Windows

Install Git and Python 3.12 64-bit on the development PC. In PowerShell:

```powershell
git clone https://github.com/MeAngela-spec/NCSC-RO1_Project.git
cd NCSC-RO1_Project
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py --open-browser
```

Open `http://127.0.0.1:8765` and create the first administrator locally.
See `START-HERE.txt` for the existing application's workflows. Legacy batch
launchers expect the offline wheels supplied in the previous ZIP distribution;
those third-party packages are not committed here. The commands above install
dependencies for development. They are not the planned end-user installation.

## Update a local checkout

Run inside the cloned `NCSC-RO1_Project` folder:

```powershell
git status
git pull --ff-only origin main
```

Stop the running application before updating its source. Back up the entire
local `data` folder before an application or database upgrade. Git updates
source files; it does not replace or synchronize office records.

## Repository workflow

Requested changes are edited and checked, committed and pushed to `main`
without an additional confirmation when repository policy allows it. Each
completed update reports its commit and the pull command above. This happens
during project work; it is not a background watcher of the developer's laptop.

Office databases, accounts, recovery codes, uploads, `.venv`, build output and
installers are excluded from Git. Test and release artifacts should be provided
through the release/build process, never by committing live records.

## Source check

```powershell
py -3.12 -m compileall -q app.py intake.py matrix_print.py print_jobs.py reports.py routing.py
```

Windows installation, office networking and physical printer output must be
verified on the target computers before office rollout.
