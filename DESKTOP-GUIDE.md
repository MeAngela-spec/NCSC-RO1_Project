# NCSC RO1 Windows installer

The shared workspace works without internet hosting. It uses the office LAN
or Wi-Fi. The chosen host PC stores the database and attachments; department
PCs connect to it. A sleeping, switched-off or disconnected host is unavailable.

## Install

Download a **successful, verified** Windows build from this repository's
Actions page. Extract the artifact ZIP and run `NCSC-RO1-Setup-0.1.0.exe`.
Python, packages and a private document-to-PDF converter are included. No pip,
Python setup or separate Word / LibreOffice installation is required.
The installer does not change existing Office installations or file associations.
It uses the installed Edge or Chrome browser as the document workspace window.

This initial installer is an unsigned office test build. Windows/agency policy
may require IT approval. Verify its SHA-256 using the included SHA256SUMS.txt.
Do a host/client and printer trial before office rollout.

## Set up the host once

1. Choose one PC that can remain on and connected during office hours.
2. Install, open the NCSC RO1 shortcut and choose **Host workspace on this PC**.
3. If migrating, stop the old app and use **Import previous data folder** before
   starting a new workspace. Choose the old folder containing register.sqlite3.
   The original is kept; an existing new workspace is never overwritten.
4. Leave port 8765 unless agency IT selects another available port. Choose
   **Save & open workspace**.
5. Create the first administrator in the local workspace window. Remote PCs
   cannot claim the initial administrator account.
6. Create the individual staff accounts and assign departments / access.
7. Copy the staff connection address shown in the host control window.
8. Allow the app through Windows Firewall on the office **Private network**.
   Agency IT may need to allow the chosen TCP port within the office LAN.
9. Minimize the host control window to keep sharing. Its close button minimizes
   it as well. **Stop & exit** finishes active requests and stops the workspace.

Idle sleep prevention leaves the display free to turn off. It cannot override
shutdown, a forced sleep command, a closed-lid sleep policy or disconnection.
The optional Windows-startup shortcut starts when that Windows user signs in;
it does not run the host before Windows sign-in or as a Windows service.

## Connect department PCs

1. Run the installer and open the NCSC RO1 shortcut.
2. Choose **Connect to office host** and paste its address, such as
   `http://192.168.1.20:8765`.
3. Use **Test connection**, then **Save & open workspace** and sign in.
4. Later launches reuse that saved address. Client PCs do not create another
   database or copy office records. They need the reachable host to work.

If the host address changes, open **Connection settings** in the Start menu.
Using a stable host address reserved by agency IT avoids re-entering an address
on each department PC. Hosting settings must be changed while the host is stopped.

## Data, backup and updates

Each host user's workspace is separate from the installed program:

```text
%LOCALAPPDATA%\NCSCRO1\data
%LOCALAPPDATA%\NCSCRO1\connection.json
%LOCALAPPDATA%\NCSCRO1\logs
```

**Create backup** makes a consistent database-and-files ZIP. Keep backups
secure: they include accounts, activity and documents. To import a backup into
a fresh installation, extract it and select its `data` folder. It will not
overwrite a workspace that has already been created.

For updates, make a backup, stop the host using **Stop & exit**, then install
the newer installer. The separate data folder is retained; database upgrades
run when the host starts. Uninstalling the app also leaves office data intact.

## Developer updates

Inside an existing source clone:

```powershell
git pull --ff-only origin main
```

Git updates source only. It does not update an already installed executable or
synchronize office records. A new Windows installer build updates the installed
app. Do not put the live database or uploaded office files into GitHub.

## Building

On Windows x64 with Python 3.12, Visual Studio release CRT files, and Inno Setup:

```powershell
python -m pip install -r requirements-build.txt
./packaging/build-windows.ps1
```

The build downloads/validates the official converter, packages the app, tests
the frozen executable, compiles the installer, installs it into an isolated
folder and tests the installed executable. These checks use fictional records
and temporary directories. The first build needs internet; the resulting
installer and application do not need internet for local office functions.

The Windows installer retains the existing browser-based interface. Native
Windows print dialogs and physical printer output still need a device trial.
