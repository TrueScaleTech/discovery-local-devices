; Inno Setup script for Discovery Now.
;
; Build it after packaging/build-windows.ps1 has produced the app folder:
;   iscc /DAppVersion=0.1.0 /DSourceDir=..\dist\DiscoveryNow packaging\installer.iss
;
; It installs for the current user only, so nobody has to approve an
; administrator prompt to install a tool that needs no administrator rights to run.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\DiscoveryNow"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

#define AppName "Discovery Now"
#define AppPublisher "TrueScaleTech"
#define AppUrl "https://github.com/TrueScaleTech/discovery-local-devices"
#define AppExe "DiscoveryNow.exe"

[Setup]
AppId={{8E6B5A4C-2F3D-4B1E-9C7A-DISCOVERYNOW}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
VersionInfoVersion={#AppVersion}

; Per-user: no administrator prompt, and nothing is written outside the user's
; own profile.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
AllowNoIcons=yes

LicenseFile=..\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=DiscoveryNow-{#AppVersion}-setup
SetupIconFile=..\dist\discovery-now.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; The app reads its own network and writes only to the user's own folders.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a shortcut on the desktop"; \
    GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The inventory and the settings are the user's own data and are left alone on
; uninstall; only what the installer put there is removed.
Type: dirifempty; Name: "{app}"
