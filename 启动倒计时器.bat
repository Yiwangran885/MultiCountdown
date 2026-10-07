@echo off
chcp 65001 >nul
rem 双击此文件启动「多倒计时器」（无黑窗口）
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0multi_timer.py"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        start "" python "%~dp0multi_timer.py"
    ) else (
        echo Python not found. Please install Python 3 and enable "Add to PATH".
        pause
    )
)
