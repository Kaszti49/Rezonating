' Runs a launcher script (default Start-RezonatingLab.ps1) without a console window; the shortcuts point here.
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
name = "Start-RezonatingLab.ps1"
If WScript.Arguments.Count > 0 Then name = WScript.Arguments(0)
CreateObject("WScript.Shell").Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & here & "\" & name & """", 0, False
