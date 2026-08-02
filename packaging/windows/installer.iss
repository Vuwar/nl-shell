; Inno Setup script - wraps the PyInstaller folder into one downloadable .exe.
;
; Built by .github/workflows/release.yml after PyInstaller, but it runs by hand
; too once you have Inno Setup 6:
;
;     iscc /DAppVersion=0.1.0 /DDistDir="..\..\dist\AI Shell" packaging\windows\installer.iss
;
; Why an installer at all, when PyInstaller can emit a single .exe: a onefile
; build unpacks its whole 40MB to a temp folder on every launch - seconds of
; delay, and a behaviour pattern antivirus heuristics dislike, which matters
; more than usual for an app whose job is running shell commands. This gets the
; same one-file download with none of that.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
; Windows' version resource is four numbers and nothing else, so a version like
; 0.2.0-rc1 can't go in it. The caller passes the numeric part separately and
; AppVersion keeps the full string everywhere a person reads it.
#ifndef VersionInfo
  #define VersionInfo AppVersion
#endif
#ifndef DistDir
  #define DistDir "..\..\dist\AI Shell"
#endif

#define AppName "AI Shell"
#define AppPublisher "Vuwar"
#define AppUrl "https://github.com/Vuwar/nl-shell"
#define AppExe "AI Shell.exe"

[Setup]
; Never change AppId - it's the identity Windows matches an upgrade against,
; and a new one turns every future release into a second parallel install.
AppId={{8F3A2D14-6C7B-4E59-9A2F-5D8E1B0C7A43}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
VersionInfoVersion={#VersionInfo}

; Per-user install: no UAC prompt, no administrator, and nothing written
; outside the user's own profile. It matches how the app already behaves -
; ai_shell.runtime installs llama.cpp into %APPDATA% rather than Program Files
; precisely so that none of this needs elevation.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}

OutputDir=..\..\dist\installer
OutputBaseFilename=AI-Shell-{#AppVersion}-windows-x64-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; PyInstaller's folder only; the user's models and settings in %APPDATA%\ai-shell
; are deliberately left alone. Several gigabytes of downloaded weights should
; not disappear because somebody uninstalled to reinstall a newer build - and
; the README says where they are for anyone who does want them gone.
Type: filesandordirs; Name: "{app}\_internal"

[Code]
{ ---- WebView2 ----------------------------------------------------------- }
{ The window is a WebView2 control. Windows 11 and any reasonably patched
  Windows 10 already have the Evergreen runtime, so this is a no-op for most
  people - but where it's missing the app opens a blank window and says
  nothing useful, which is a bad first five seconds. The bootstrapper is ~2MB
  and pulls the rest itself. }

const
  WebView2ClientKey = 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2BootstrapUrl = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703';

var
  DownloadPage: TDownloadWizardPage;

function WebView2Installed(): Boolean;
var
  Version: String;
begin
  { Machine-wide (the usual case, and 32-bit view on 64-bit Windows) or
    per-user - a runtime installed either way is one we can use. }
  Result :=
    (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM, WebView2ClientKey, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKCU, WebView2ClientKey, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  Result := True;
end;

procedure InitializeWizard();
begin
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing), SetupMessage(msgPreparingDesc), @OnDownloadProgress);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID <> wpReady) or WebView2Installed() then
    Exit;

  DownloadPage.Clear;
  DownloadPage.Add(WebView2BootstrapUrl, 'MicrosoftEdgeWebview2Setup.exe', '');
  DownloadPage.Show;
  try
    try
      DownloadPage.Download;
    except
      { Not fatal. The install is still perfectly good on a machine that gets
        the runtime some other way - through Windows Update, or by the user
        installing Edge - and refusing to continue over a failed optional
        download would be worse than letting them try. }
      if SuppressibleMsgBox(
        'The WebView2 runtime could not be downloaded:' + #13#10#13#10 + GetExceptionMessage + #13#10#13#10 +
        'AI Shell needs it to draw its window. Install anyway and sort it out later?',
        mbError, MB_YESNO, IDYES) <> IDYES then
        Result := False;
    end;
  finally
    DownloadPage.Hide;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ExitCode: Integer;
  Bootstrapper: String;
begin
  if CurStep <> ssPostInstall then
    Exit;

  Bootstrapper := ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe');
  if not FileExists(Bootstrapper) then
    Exit;

  { /silent so the runtime install doesn't put a second wizard in front of
    ours. Its own failures are reported by exit code and nothing else, so an
    unhappy one is worth surfacing rather than swallowing. }
  if not Exec(Bootstrapper, '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) then
    SuppressibleMsgBox(
      'The WebView2 runtime installer did not finish cleanly (code ' + IntToStr(ExitCode) + ').' + #13#10#13#10 +
      'If AI Shell opens an empty window, install "Microsoft Edge WebView2 Runtime" from Microsoft and try again.',
      mbInformation, MB_OK, IDOK);
end;
