"""PyInstaller 打包脚本：把 ScanMaster 打包成单个 exe。

运行: python build_exe.py
产物: dist/ScanMaster/ScanMaster.exe
"""
import subprocess
import sys
import os

CMD = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", "ScanMaster",
    "--icon", "NONE",
    # RapidOCR 的 ONNX 模型与 opencv 数据需一并打包
    "--collect-all", "rapidocr_onnxruntime",
    "--collect-all", "cv2",
    "--hidden-import", "fitz",
    "--hidden-import", "docx",
    "--hidden-import", "openpyxl",
    "main.py",
]


def main():
    print("开始打包 ScanMaster ...")
    result = subprocess.run(CMD, cwd=os.path.dirname(os.path.abspath(__file__)))
    if result.returncode == 0:
        print("\n打包完成: dist/ScanMaster/ScanMaster.exe")
    else:
        print(f"\n打包失败，退出码: {result.returncode}")
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
