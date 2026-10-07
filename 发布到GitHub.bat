@echo off
chcp 65001 >nul
cd /d "%~dp0"

where gh >nul 2>nul
if errorlevel 1 (
    echo [!] 未找到 gh，请先执行: winget install GitHub.cli
    pause
    exit /b 1
)

gh auth status >nul 2>&1
if errorlevel 1 (
    echo 需要登录 GitHub，按提示用浏览器完成授权...
    gh auth login -h github.com -w
    if errorlevel 1 (
        echo 登录失败，退出。
        pause
        exit /b 1
    )
)

echo.
echo [1/2] 创建仓库并推送源码...
gh repo create MultiCountdown --public --source . --push --description "多任务倒计时器 · Windows 桌面小工具：多计时倒计时 + 日期倒数（生日/考研）+ 毛玻璃 UI"
if errorlevel 1 (
    echo 仓库可能已存在，改为直接推送...
    git push -u origin main
    if errorlevel 1 (
        echo 推送失败，请检查网络或权限。
        pause
        exit /b 1
    )
)

echo.
echo [2/2] 创建 Release v1.0.0 并上传安装包...
gh release create v1.0.0 --title "v1.0.0" --notes-file RELEASE_NOTES.md "_release\MultiCountdown_Setup_1.0.0.exe" "_release\MultiCountdown_1.0.0_win64_portable.zip"
if errorlevel 1 (
    echo Release 创建失败（可能已存在）。
    pause
    exit /b 1
)

echo.
echo 完成！仓库与 Release 已发布。
pause
