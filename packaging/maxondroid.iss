; Inno Setup script for MaxOnDroid: a per-user installer in Russian and English.
;   ISCC.exe /DAppVersion=0.9.0 /DSourceDir=..\dist\MaxOnDroid packaging\maxondroid.iss
; SourceDir is the PyInstaller folder with tools\scrcpy already copied in (see release.yml).
;
; The installer never asks for administrator rights. By default it puts the program in
; %LOCALAPPDATA%\Programs\MaxOnDroid. A folder that needs administrator rights
; (Program Files, Windows, ProgramData) is refused with an explanation, both on the
; folder page and, for silent installs with /DIR, before anything is copied.

#ifndef AppVersion
  #error Pass the version: ISCC /DAppVersion=X.Y.Z
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\MaxOnDroid"
#endif
#define AppName "MaxOnDroid"
#define AppExe "MaxOnDroid.exe"
#define Repo "https://github.com/mgrigorev183-arch/MaxOnDroid"

[Setup]
; Never change AppId: Windows uses it to recognise updates and the uninstaller.
AppId={{402AB4A8-83CF-4C9F-97D5-55D3693A4B02}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
AppPublisherURL={#Repo}
AppSupportURL={#Repo}/issues
AppUpdatesURL={#Repo}/releases
AppCopyright=GPL-3.0-only
VersionInfoVersion={#AppVersion}.0
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DisableDirPage=no
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile=..\LICENSE
SetupIconFile=maxondroid.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVersion}
WizardStyle=modern
ShowLanguageDialog=auto
OutputDir=..\dist\installer
OutputBaseFilename=MaxOnDroid-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
russian.AdminFolder=Для папки «%1» нужны права администратора.%n%nMaxOnDroid ставится только для вас и без прав администратора, поэтому Program Files, Windows и ProgramData не подходят. Выберите папку в своём профиле, например:%n%2
english.AdminFolder=The folder "%1" needs administrator rights.%n%nMaxOnDroid installs for you only and without administrator rights, so Program Files, Windows and ProgramData cannot be used. Choose a folder in your profile, for example:%n%2
russian.NotWritable=В папку «%1» нельзя записать файлы под вашей учётной записью. Выберите другую папку, например:%n%2
english.NotWritable=Your account cannot write to the folder "%1". Choose another folder, for example:%n%2
russian.RemoveData=Удалить и ваши данные MaxOnDroid?%n%nЭто настройки, список устройств, журналы, загруженный список пакетов и резервные копии APK:%n%1%n%2%n%nСкриншоты и записи экрана в папке «Изображения» не удаляются.
english.RemoveData=Also delete your MaxOnDroid data?%n%nThis is the settings, the device list, logs, the downloaded package list and APK backups:%n%1%n%2%n%nScreenshots and screen recordings in your Pictures folder are kept.
russian.DesktopIcon=Значок на рабочем столе
english.DesktopIcon=Desktop shortcut

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; an update replaces the whole program folder content, so files dropped by a newer build do not linger
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\tools"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
function IsUnder(const Path, Root: String): Boolean;
var
  P, R: String;
begin
  Result := False;
  if Root = '' then
    Exit;
  P := AddBackslash(Lowercase(ExpandFileName(Path)));
  R := AddBackslash(Lowercase(ExpandFileName(Root)));
  Result := Copy(P, 1, Length(R)) = R;
end;

function NeedsAdmin(const Dir: String): Boolean;
begin
  Result := IsUnder(Dir, ExpandConstant('{commonpf32}'))
    or IsUnder(Dir, ExpandConstant('{commonpf64}'))
    or IsUnder(Dir, ExpandConstant('{win}'))
    or IsUnder(Dir, ExpandConstant('{commonappdata}'));
end;

function NearestExistingDir(const Dir: String): String;
var
  Parent: String;
begin
  Result := RemoveBackslashUnlessRoot(ExpandFileName(Dir));
  while (Result <> '') and not DirExists(Result) do
  begin
    Parent := ExtractFileDir(Result);
    if Parent = Result then
    begin
      Result := '';
      Exit;
    end;
    Result := Parent;
  end;
end;

function CanWrite(const Dir: String): Boolean;
var
  Existing, Probe: String;
begin
  Existing := NearestExistingDir(Dir);
  Result := False;
  if Existing = '' then
    Exit;
  Probe := AddBackslash(Existing) + 'maxondroid-write-test.tmp';
  Result := SaveStringToFile(Probe, 'MaxOnDroid', False);
  if Result then
    DeleteFile(Probe);
end;

function FolderProblem(const Dir: String): String;
var
  Suggested: String;
begin
  Result := '';
  Suggested := ExpandConstant('{localappdata}\Programs\{#AppName}');
  if NeedsAdmin(Dir) then
    Result := FmtMessage(CustomMessage('AdminFolder'), [Dir, Suggested])
  else if not CanWrite(Dir) then
    Result := FmtMessage(CustomMessage('NotWritable'), [Dir, Suggested]);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Problem: String;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    Problem := FolderProblem(WizardDirValue);
    if Problem <> '' then
    begin
      MsgBox(Problem, mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure StopBundledAdb(const AppDir: String);
var
  Adb: String;
  Code: Integer;
begin
  { the adb server started by MaxOnDroid keeps adb.exe open; stop it so the files can be replaced }
  Adb := AddBackslash(AppDir) + 'tools\scrcpy\adb.exe';
  if FileExists(Adb) then
    Exec(Adb, 'kill-server', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  { also covers silent installs with /DIR, where no folder page is shown }
  Result := FolderProblem(ExpandConstant('{app}'));
  if Result = '' then
    StopBundledAdb(ExpandConstant('{app}'));
end;

function InitializeUninstall(): Boolean;
begin
  StopBundledAdb(ExpandConstant('{app}'));
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Settings, Local: String;
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
  begin
    Settings := ExpandConstant('{userappdata}\{#AppName}');
    Local := ExpandConstant('{localappdata}\{#AppName}');
    if (DirExists(Settings) or DirExists(Local)) and
       (MsgBox(FmtMessage(CustomMessage('RemoveData'), [Settings, Local]), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
    begin
      DelTree(Settings, True, True, True);
      DelTree(Local, True, True, True);
    end;
  end;
end;
