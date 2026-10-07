# MultiCountdown · 多倒计时器

> Windows 桌面倒计时小工具：多计时倒计时 + 日期倒数（生日 / 考研 / 纪念日），毛玻璃半透明 UI，纯 Python + Tkinter 实现。

![screenshot](docs/screenshot.png)

## ✨ 功能

- **计时倒计时**：任意数量、独立命名，卡片显示剩余时间与实时进度条
- **同时只计时一个**：启动新的会自动暂停正在计时的那个，保留进度随时接续
- **日期倒计时**：指定目标日期按天倒数，支持「每年重复」（生日到期自动滚到下一年，2 月 29 日自动按 28 日处理）
- **📌 置顶**：重要日期固定在窗口顶部，滚动列表也不动
- **每日自动重置**：跨天后所有计时恢复满时长（适合每天固定的专注时段）
- **卡片外观**：每张卡片可自定义背景颜色或图片，文字明暗自动适配
- **三档界面**：毛玻璃透明（Win11 亚克力，自动降级）/ 半透明 / 不透明
- **窗口置顶** 与 **开机自启动**：设置里一键勾选
- 计时结束：提示音 + 窗口置顶提醒；数据自动保存、重启恢复

## 📥 下载安装

到 [Releases](../../releases) 页面下载：

| 文件 | 说明 |
| --- | --- |
| `MultiCountdown_Setup_1.0.0.exe` | 安装版：自动创建桌面 / 开始菜单快捷方式，带卸载器 |
| `MultiCountdown_1.0.0_win64_portable.zip` | 绿色便携版：解压即用，无需安装 |

> 便携版请解压到**可写目录**使用——数据文件（`timers.json` / `settings.json`）保存在程序同目录。

## 🚀 从源码运行

需要 Windows 10/11 与 Python 3.10+：

```bash
pip install pillow
python multi_timer.py
```

或直接双击 `启动倒计时器.bat`（无黑窗口启动）。

## 🔨 自行打包

```bash
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --icon timer_icon.ico --name MultiCountdown multi_timer.py
```

## 🧪 内置自检

```bash
python multi_timer.py --selftest
```

覆盖计时互斥、暂停恢复、跨天重置、数据兼容、对话框构建等断言。

## License

[MIT](LICENSE)
