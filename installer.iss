[Setup]
AppName=Extractarr
AppVersion=1.0.0
DefaultDirName={autopf}\Extractarr
DefaultGroupName=Extractarr
UninstallDisplayIcon={app}\extractarr-service.exe
Compression=lzma2
SolidCompression=yes
OutputBaseFilename=ExtractarrSetup
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
AppPublisher=Nat20labs
AppPublisherURL=https://buymeacoffee.com/Nat20labs

[Files]
Source: "dist\extractarr-service\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Run]
; Install the service using pywin32's built-in command
Filename: "{app}\extractarr-service.exe"; Parameters: "--startup auto install"; Flags: runhidden waituntilterminated
; Start the service
Filename: "net.exe"; Parameters: "start Extractarr"; Flags: runhidden waituntilterminated

[UninstallRun]
; Stop the service before uninstalling
Filename: "net.exe"; Parameters: "stop Extractarr"; Flags: runhidden waituntilterminated; RunOnceId: "StopService"
; Remove the service
Filename: "{app}\extractarr-service.exe"; Parameters: "remove"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveService"
