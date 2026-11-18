Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "F:\darkshadow"
WshShell.Run "py wake_daemon.py", 0, False
