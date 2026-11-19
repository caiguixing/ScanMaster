# ScanMaster 智能文档扫描工具

一个本地离线的桌面文档处理工具，类似"夸克扫描王"的核心能力：拖拽导入图片/PDF，自动扫描矫正、提取文字、转换成 Office 文档。**全部识别在本地完成，不上传任何数据。**

## 功能

- **文档扫描矫正** — 自动检测文档边缘、透视变换拉正、去阴影二值化，输出干净扫描件
- **提取文字** — 本地 OCR 识别，按阅读顺序排列，带置信度，导出 TXT
- **图片转 Word** — 原扫描图 + 识别文字生成 `.docx`
- **PDF 转 Word** — 逐页渲染并 OCR，汇总为一个 Word 文档
- **表格转 Excel** — 根据文字坐标重建表格，导出 `.xlsx`
- **多种导入方式** — 文件拖拽、剪贴板粘贴、文件选择对话框

## 安装与运行

```bash
# 1. 安装依赖（Python 3.10+，推荐 3.11/3.12）
pip install -r requirements.txt

# 2. 启动
python main.py
```

> 说明：Python 3.13 下 PaddlePaddle 支持不佳，本项目采用 **RapidOCR**（PaddleOCR 模型的 ONNX 离线移植版），无需 `paddlepaddle`，识别效果一致且兼容性更好。

## 打包为 exe

```bash
python build_exe.py
# 产物：dist/ScanMaster/ScanMaster.exe
```

## 使用方法

1. 打开软件后，把图片/PDF **拖进窗口**，或点击「导入文件」/「粘贴剪贴板」
2. 在右侧查看文件预览与列表
3. 点击底部功能按钮执行对应操作
4. 处理结果自动保存到输出目录（默认 `桌面/ScanMaster_Output`），并自动打开

## 项目结构

```
ScanMaster/
├── main.py                  # 程序入口
├── requirements.txt         # 依赖清单
├── build_exe.py             # 打包脚本
├── app/
│   ├── main_window.py       # PySide6 主界面
│   ├── worker.py            # 后台任务线程
│   ├── scanner.py           # 文档扫描矫正引擎 (OpenCV)
│   ├── ocr_engine.py        # 本地 OCR 封装 (RapidOCR)
│   └── exporters.py         # TXT/Word/Excel 导出
└── tests/
    └── smoke_test.py        # 核心模块冒烟测试
```

## 测试

```bash
python tests/smoke_test.py
```

## 技术栈

PySide6 · OpenCV · RapidOCR(ONNX) · python-docx · openpyxl · PyMuPDF

## License

MIT
