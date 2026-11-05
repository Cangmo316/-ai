' 比邻AI 后端启动器（VBS 脱离会话，不需要管理员）
' 为什么用 VBS：Start-Process 的子进程会随父进程被回收（实测服务反复"自己停"），
' WScript.Shell.Run 配合 False 不等待，进程会挂到 explorer 下，不受终端影响。
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "E:\比邻AI\server"
sh.Run """E:\比邻AI\server\.venv\Scripts\python.exe"" run.py", 0, False