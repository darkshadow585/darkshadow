Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "F:\darkshadow"
WshShell.Run "py main.py", 0, False
