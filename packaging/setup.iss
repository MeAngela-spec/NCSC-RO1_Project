#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif
[Setup]
AppId={{2D1EF50A-9D44-4A13-AE13-0FC5B28314A7}
AppName=NCSC RO1 Document Routing and Tracking
AppVersion={#AppVersion}
AppPublisher=NCSC RO1 Project
AppPublisherURL=https://github.com/MeAngela-spec/NCSC-RO1_Project
DefaultDirName={localappdata}\Programs\NCSCRO1
DefaultGroupName=NCSC RO1
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
AppMutex=Local\NCSCRO1Desktop
SetupIconFile=..\assets\ncsc.ico
UninstallDisplayIcon={app}\NCSCRO1.exe
OutputDir=..\installer-output
OutputBaseFilename=NCSC-RO1-Setup-{#AppVersion}
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=no
InfoBeforeFile=installer-info.txt

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start when I sign in to Windows (useful on the host PC)"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "..\dist\NCSCRO1\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\NCSC RO1"; Filename: "{app}\NCSCRO1.exe"; AppUserModelID: "NCSC.RO1.DocumentTracking"
Name: "{group}\Connection settings"; Filename: "{app}\NCSCRO1.exe"; Parameters: "--configure"
Name: "{group}\Desktop guide"; Filename: "{sys}\notepad.exe"; Parameters: """{app}\_internal\DESKTOP-GUIDE.md"""
Name: "{autodesktop}\NCSC RO1"; Filename: "{app}\NCSCRO1.exe"; Tasks: desktopicon
Name: "{userstartup}\NCSC RO1"; Filename: "{app}\NCSCRO1.exe"; Tasks: startup

[Run]
Filename: "{app}\NCSCRO1.exe"; Description: "Open NCSC RO1"; Flags: nowait postinstall skipifsilent runasoriginaluser

; Never uninstall or overwrite the separate user's workspace data directory.
