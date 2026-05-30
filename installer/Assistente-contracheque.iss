#define AppName "Assistente-contracheque"
#define AppVersion "2.0.0"
#define AppExeName "Assistente-contracheque.exe"

[Setup]
AppId={{DDF3EE8B-9F2F-41DF-8E2C-5E63B1A2F9C7}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Gestao de Carreira
DefaultDirName={localappdata}\GestaoDeCarreira\AssistenteContracheque
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=Assistente-contracheque-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na area de trabalho"; GroupDescription: "Atalhos:"

[InstallDelete]
Type: filesandordirs; Name: "{app}\*"

[Files]
Source: "..\dist\Assistente-contracheque\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Classes\gestaodecarreira"; ValueType: string; ValueName: ""; ValueData: "URL:Gestao de Carreira"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\gestaodecarreira"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\gestaodecarreira\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Flags: uninsdeletekey

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Abrir Assistente-contracheque agora"; Flags: nowait postinstall skipifsilent
