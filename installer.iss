; 大肥鱼桌宠 · Windows 安装包脚本（Inno Setup 6）
; 编译：ISCC.exe /DMyAppVersion=1.0.14 installer.iss
; 产物：dist\大肥鱼桌宠-安装版-v1.0.14.exe
; 特点：双击运行 → 中文向导，能选安装位置（默认装到"当前用户"目录，不弹 UAC）、
;       建桌面/开始菜单快捷方式、在"设置 → 应用"里能卸载，装完安装包本身就能删。

#define MyAppName "大肥鱼桌宠"
#define MyAppExeName "大肥鱼桌宠.exe"
#define MyAppPublisher "RYANFFY"
#define MyAppURL "https://github.com/RYANFFY/deepseek-dafeiyu-pet"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef MyLangFile
  #define MyLangFile "F:\Codex\tools\innosetup-lang\ChineseSimplified.isl"
#endif

[Setup]
AppId={{8F3A6D1C-2E44-4F0B-9C77-2A5B7E9D1C31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoDescription={#MyAppName} 安装程序
DefaultDirName={localappdata}\Programs\大肥鱼桌宠
DefaultGroupName=大肥鱼桌宠
DisableProgramGroupPage=no
DisableDirPage=no
AllowNoIcons=yes
OutputDir=dist
OutputBaseFilename=大肥鱼桌宠-安装版-v{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ShowLanguageDialog=no

[Languages]
Name: "cn"; MessagesFile: "{#MyLangFile}"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："
Name: "startmenu"; Description: "创建开始菜单快捷方式"; GroupDescription: "附加任务："

[Files]
; 目录版（onedir）：整个文件夹装进去（含 _internal 那一堆依赖）。
; 以前是单文件 exe，每次启动都要先解压 100 多 MB 到临时目录，启动慢；
; 改成文件夹版之后启动快很多，用户那边还是双击同一个快捷方式。
Source: "dist\大肥鱼桌宠\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\大肥鱼桌宠"; Filename: "{app}\{#MyAppExeName}"; Tasks: startmenu
Name: "{autodesktop}\大肥鱼桌宠"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立刻运行大肥鱼桌宠"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Name: "{app}"; Type: filesandordirs
