# NCSC-RO1_Project
Document Routing and Tracking System

Python document routing and tracking for NCSC Regional Office I. The starting
source is the `NCSC_RO1.zip` supplied on 24 November 2026. Existing document
flows, NCSC assets, routing-slip template and sample files are retained.

## Current application

- Individual staff logins, personal/shared document access and grouped accounts.
- Persistent department registration and permanent archived-login removal that
  preserves audit history and keeps private assignments restricted.
- Separate staff inbox reports, department-level shared acknowledgements and private-assignment acknowledgements.
- Year filters on dashboard/register/deleted documents, with retained review comments and attributed history.
- Drag-and-drop source import and multiple supporting-file uploads.
- Centered 10 pt routing entries, Action Taken remarks, and bounded preview/print caches.
- Department dashboard summaries and six status counters with matching filters.
- Sequential yearly references in the format `RO1-MEMO-YYYY-00001`.
- Departments sidebar folders with document counts; optional staff assignment
  filtered by the selected department and validated by the host.
- Adaptive Excel / CSV and document imports, including saved email intake.
- Document viewing, editing, routing, requested actions, status and MOV files.
- Excel / Word / PDF reports, readable print matrices and original-template slips,
  including print-only text editing before printing a shared multi-document slip.
- Bulk source selection/deletion, filtered Select all, batch restoration and
  administrator-only permanent deletion with confirmation and version checks.
- Status choices: For routing, Received, Pending, Ongoing, Completed, For Comment,
  For Signature and Other / specify. Password changes verify the generated
  recovery code and display a replacement code after success.
- SQLite database and supporting files stored together in a local `data` folder.

The current interface opens in a browser served by Python on the host computer.
It works without internet for local records and files. Internet links require
their own service access. Several departments sharing one workspace need a
reachable office LAN and an awake host; installing separate database copies
does not automatically synchronize them.

## Windows installer

The chosen setup is a shared workspace over the office LAN. `desktop.py` adds
host/client connection settings, a persistent data directory, host controls,
safe existing-data import and consistent backup. The Windows build bundles
Python, application dependencies and a private print converter. Office users
do not install Python or run pip themselves.

The Actions workflow builds on Windows and verifies both the frozen executable
and the installed application before uploading an installer artifact. Download
only a successful build's **NCSC-RO1-Windows-Installer** artifact. A source
commit alone is not evidence of a completed installer. See [DESKTOP-GUIDE.md](DESKTOP-GUIDE.md)
for setup, migration, office networking and updates.

For source development, exact-template PDF conversion can use locally installed
Word or LibreOffice. The full Windows installer includes its own converter.
The program retains the existing browser-based document interface.

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
To run the desktop connection launcher from source, use `python desktop.py`.
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
