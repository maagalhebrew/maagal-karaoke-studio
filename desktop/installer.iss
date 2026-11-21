[Setup]
; Test installs exercise this payload in an isolated folder without registering it.
AppId={{7EE65B81-751A-46B5-948B-B0520E415B53}
AppName=Maagal Karaoke Studio
AppVersion=2.0
AppPublisher=Maagal Hebrew
AppPublisherURL=https://maagalhebrew.com/
DefaultDirName={localappdata}\Programs\Karaoke IL
DefaultGroupName=Maagal Karaoke Studio
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
#ifdef PrivateQA
Compression=none
SolidCompression=no
#else
Compression=lzma2/fast
SolidCompression=yes
#endif
WizardStyle=modern
OutputDir=..\release
#ifdef PrivateQA
AppVerName=Maagal Karaoke Studio (Private QA)
OutputBaseFilename=Maagal-Karaoke-Studio-Windows-Setup-PRIVATE-QA
DiskSpanning=yes
DiskSliceSize=max
#else
OutputBaseFilename=Maagal-Karaoke-Studio-Windows-Setup
#endif
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\Karaoke IL.exe
CloseApplications=yes
Uninstallable=not IsQARun
CreateUninstallRegKey=not IsQARun

[Files]
Source: "{#StudioPayload}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

#ifdef PrivateQA
Source: "{#StudioPayload}\..\PRIVATE-QA.txt"; DestDir: "{app}"; Flags: ignoreversion
#endif

[Icons]
Name: "{autoprograms}\Maagal Karaoke Studio"; Filename: "{app}\Karaoke IL.exe"; Check: WriteStartShortcut
Name: "{autodesktop}\Maagal Karaoke Studio"; Filename: "{app}\Karaoke IL.exe"; Check: WriteDesktopShortcut

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\Karaoke IL.exe"; Description: "Open Maagal Karaoke Studio"; Flags: nowait postinstall skipifsilent

[Code]
function IsQARun: Boolean;
begin
  Result := ExpandConstant('{param:KaraokeTest|0}') = '1';
end;

function TargetsInstalledApp(const ShortcutPath: String): Boolean;
var
  Shell, Link: Variant;
  Target: String;
begin
  Result := False;
  if not FileExists(ShortcutPath) then
    Exit;
  try
    Shell := CreateOleObject('WScript.Shell');
    Link := Shell.CreateShortcut(ShortcutPath);
    Target := Link.TargetPath;
    Result := CompareText(Target, ExpandConstant('{app}\Karaoke IL.exe')) = 0;
  except
    Log('Could not verify shortcut target: ' + ShortcutPath);
  end;
end;

function CanWriteShortcut(const ShortcutPath: String): Boolean;
begin
  Result := not FileExists(ShortcutPath) or TargetsInstalledApp(ShortcutPath);
end;

function WriteStartShortcut: Boolean;
begin
  Result := False;
  if not IsQARun then
    Result := CanWriteShortcut(ExpandConstant('{autoprograms}\Maagal Karaoke Studio.lnk'));
end;

function WriteDesktopShortcut: Boolean;
begin
  Result := False;
  if not IsQARun then
    Result := CanWriteShortcut(ExpandConstant('{autodesktop}\Maagal Karaoke Studio.lnk')) and
      (WizardIsTaskSelected('desktopicon') or
       TargetsInstalledApp(ExpandConstant('{autodesktop}\Karaoke IL.lnk')));
end;

procedure RetireLegacyShortcut(const OldPath, NewPath: String);
begin
  if TargetsInstalledApp(OldPath) and TargetsInstalledApp(NewPath) then
    if not DeleteFile(OldPath) then
      Log('Could not retire the old shortcut: ' + OldPath);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and not IsQARun then
  begin
    RetireLegacyShortcut(ExpandConstant('{autoprograms}\Karaoke IL.lnk'),
                         ExpandConstant('{autoprograms}\Maagal Karaoke Studio.lnk'));
    RetireLegacyShortcut(ExpandConstant('{autodesktop}\Karaoke IL.lnk'),
                         ExpandConstant('{autodesktop}\Maagal Karaoke Studio.lnk'));
  end;
end;
