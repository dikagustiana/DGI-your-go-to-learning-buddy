; Inno Setup script for "PDF ke Excel".
;
; Build order (see BUILD.md):
;   1. pyinstaller pdf2excel.spec --noconfirm     -> dist\pdf2excel\
;   2. ISCC.exe installer\setup.iss               -> installer\Output\PDF-ke-Excel-Setup.exe
;
; Design goals for elderly, non-technical users:
;   * installs per-user under %LOCALAPPDATA%\Programs — NO admin rights,
;     no UAC prompt;
;   * plain Next -> Next -> Finish wizard in Indonesian;
;   * Start Menu + Desktop shortcuts, launch on finish;
;   * clean uninstaller registered in Windows "Apps & features".

#define MyAppName "PDF ke Excel"
#define MyAppVersion "1.0.0"
#define MyAppExeName "pdf2excel.exe"

[Setup]
; Fixed AppId so upgrades replace the same installation.
AppId={{7E1B7C1E-9A45-4B2E-B6D0-2F3A54C1D9AB}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
DefaultDirName={localappdata}\Programs\PDF ke Excel
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=PDF-ke-Excel-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "indonesian"; MessagesFile: "Indonesian.isl"

[Tasks]
; Checked by default — the desktop icon IS how the target user finds the app.
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\pdf2excel\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
