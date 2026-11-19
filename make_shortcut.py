# -*- coding: utf-8 -*-
"""在桌面创建 ScanMaster 快捷方式（无黑框、带专属图标、工作目录锁定的项目根）。"""
import os
import pythoncom
import win32com.client

DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")
LNK = os.path.join(DESKTOP, "ScanMaster.lnk")
PYW = r"C:\Users\cgx.cai\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe"
PROJ = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(PROJ, "main.py")
ICO = os.path.join(PROJ, "app_icon.ico")

shell = win32com.client.Dispatch("WScript.Shell")
sc = shell.CreateShortCut(LNK)
sc.TargetPath = PYW
sc.Arguments = '"%s"' % MAIN
sc.WorkingDirectory = PROJ
sc.IconLocation = ICO
sc.Description = "ScanMaster 智能文档扫描工具 - 扫描/OCR/转Word/转Excel"
sc.save()

# 回读验证
chk = shell.CreateShortCut(LNK)
print("路径:", LNK)
print("存在:", os.path.exists(LNK))
print("目标:", chk.TargetPath)
print("参数:", chk.Arguments)
print("工作目录:", chk.WorkingDirectory)
print("图标:", chk.IconLocation)
print("大小:", os.path.getsize(LNK), "bytes")
