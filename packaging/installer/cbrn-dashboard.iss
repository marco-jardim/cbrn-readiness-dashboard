; Inno Setup 6 script of the per-user installer of the CBRN Readiness Dashboard.
;
; Built by scripts/build_installer.py from the already tested one-folder bundle; it is never run
; by hand. The defines below come from the command line of ISCC.exe:
;   /DAppVersion=1.0.2                     the package version
;   /DBundleDir=C:\path\to\cbrn-dashboard  the folder with cbrn-dashboard.exe and _internal\
;   /DOutputDir=C:\path\to\release         where the setup .exe is written
;   /DOutputBaseFilename=cbrn-readiness-dashboard-1.0.2-win-x64-setup
;   /DVersionInfoVersion=1.0.2.0           optional, the numeric version of the setup file
;
; Rules this script keeps (tests/meta/test_installer_script.py checks them):
;  - No administrator rights are needed: PrivilegesRequired=lowest. The user may still choose an
;    all-users install in the start-up dialog (needs an administrator).
;  - The user data (%LOCALAPPDATA%\cbrn-readiness-dashboard) is never touched: there is no
;    [UninstallDelete] section and no [Files] entry that points at the data folder.
;  - portable.ini is never installed: an installed program keeps its data in the profile.
;  - No network use and no registry key except the uninstall entry that Inno Setup writes itself.
; The text of this file is ASCII on purpose (no byte order mark is needed).

#ifndef AppVersion
  #error Pass the version: ISCC /DAppVersion=1.0.2 ...
#endif
#ifndef BundleDir
  #error Pass the bundle folder: ISCC /DBundleDir=C:\path\to\cbrn-dashboard ...
#endif
#ifndef OutputDir
  #error Pass the output folder: ISCC /DOutputDir=C:\path\to\release ...
#endif
#ifndef OutputBaseFilename
  #error Pass the file name: ISCC /DOutputBaseFilename=cbrn-readiness-dashboard-1.0.2-win-x64-setup ...
#endif

#define AppName "CBRN Readiness Dashboard"
#define AppExeName "cbrn-dashboard.exe"
#define AppUrl "https://github.com/marco-jardim/cbrn-readiness-dashboard"

[Setup]
; The AppId identifies the program for upgrades and the uninstaller. It is a fixed value: never
; change it, or an upgrade would install a second copy beside the old one.
AppId={{7C3F2A58-5E1B-4D6A-9B84-2F0D1C9E6A31}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Marco Jardim
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}
AppCopyright=Source: GPL-3.0-or-later; bundle: GPL-3.0
#ifdef VersionInfoVersion
VersionInfoVersion={#VersionInfoVersion}
#endif
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} setup
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Windows 10 version 1809 (PLAN.md section 8).
MinVersion=10.0.17763
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
SetupIconFile=..\..\src\cbrn_dashboard\resources\app.ico
UninstallDisplayIcon={app}\{#AppExeName}
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
LicenseFile=..\..\LICENSE
ShowLanguageDialog=auto
; The program uses a lock file, not a named mutex, so there is no AppMutex. A running copy is
; closed through the Restart Manager before its files are replaced.
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"; InfoBeforeFile: "before-install.en-US.txt"
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"; InfoBeforeFile: "before-install.pt-BR.txt"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"; InfoBeforeFile: "before-install.es-ES.txt"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; An upgrade replaces the whole _internal folder, so that no file of the old version stays mixed
; with the new ones. This is the program folder only, never the data folder.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; Everything the tested bundle holds. portable.ini would switch the program to portable mode (data
; beside the program), which an installed copy must not do; the example file is not needed.
Source: "{#BundleDir}\*"; DestDir: "{app}"; Excludes: "portable.ini,portable.ini.example"; Flags: ignoreversion recursesubdirs createallsubdirs
; The first-run notes, as in the zip.
Source: "..\README-first-run.pt-BR.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README-first-run.en-US.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README-first-run.es-ES.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; There is deliberately no [UninstallDelete] section: the uninstaller removes the files it
; installed and nothing else. The data in %LOCALAPPDATA%\cbrn-readiness-dashboard stays.
