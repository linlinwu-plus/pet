' Bubble Cat desktop pet - silent launcher (double-click to start)
Option Explicit
Dim sh, fso, here, exe
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = here

exe = "pythonw.exe"
sh.Run """" & exe & """ """ & here & "\pet.py""", 0, False
