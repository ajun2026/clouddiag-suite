@echo off
chcp 65001 >nul
title 云端AI远程运维助手 - 桥接器卸载
setlocal enabledelayedexpansion

REM ============================================================
REM 云端 AI 远程运维助手 — Windows 桥接器卸载脚本
REM
REM 用法: 双击运行（会自动请求管理员权限），或右键"以管理员身份运行"
REM
REM 作用（只动本程序自己的文件，不碰系统其它东西）:
REM   1. 停止运行中的桥接器进程
REM   2. 删除程序文件（含历史名 bridge.exe / clouddiag-bridge*.exe）
REM   3. 删除审计日志目录 %USERPROFILE%\.clouddiag
REM ============================================================

echo ==============================================
echo  云端AI远程运维助手 · 桥接器卸载
echo ==============================================
echo.

REM ── 请求管理员权限（删除 Program Files 等目录需要）──
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo  需要管理员权限，正在请求提权...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set "FOUND=0"

REM ── 1. 停止运行中的桥接器进程 ──
echo [1/4] 停止运行中的桥接器进程...
for %%N in (clouddiag-bridge-win64.exe clouddiag-bridge.exe bridge.exe) do (
    taskkill /F /IM "%%N" >nul 2>&1
    if !errorlevel! equ 0 (
        echo   已停止进程 %%N
        set "FOUND=1"
    )
)
REM 兜底：按窗口标题/命令行匹配（历史启动方式）
powershell -NoProfile -Command ^
  "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'clouddiag-bridge|bridge-win64' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host ('  已强制停止 PID ' + $_.ProcessId) }" 2>nul
echo.

REM ── 2. 删除程序文件 ──
echo [2/4] 删除程序文件...
set "DIRS=%USERPROFILE%\Downloads %USERPROFILE%\Desktop %USERPROFILE%\DiagLogs %TEMP%\clouddiag %LOCALAPPDATA%\clouddiag C:\clouddiag"
for %%D in (%DIRS%) do (
    if exist "%%D" (
        for %%F in (clouddiag-bridge-win64.exe clouddiag-bridge.exe bridge-win64.exe bridge.exe) do (
            if exist "%%D\%%F" (
                del /F /Q "%%D\%%F" >nul 2>&1
                if not exist "%%D\%%F" (
                    echo   已删除 %%D\%%F
                    set "FOUND=1"
                )
            )
        )
    )
)

REM 用户目录下的桥接器文件夹
for %%D in ("%USERPROFILE%\.clouddiag" "%LOCALAPPDATA%\clouddiag-bridge") do (
    if exist "%%~D" (
        echo   发现目录 %%D
    )
)
echo.

REM ── 3. 删除日志与配置 ──
echo [3/4] 删除审计日志与配置...
if exist "%USERPROFILE%\.clouddiag" (
    rmdir /S /Q "%USERPROFILE%\.clouddiag" >nul 2>&1
    if not exist "%USERPROFILE%\.clouddiag" (
        echo   已删除 %USERPROFILE%\.clouddiag（含 bridge.log 审计日志）
        set "FOUND=1"
    )
) else (
    echo   未找到 %USERPROFILE%\.clouddiag
)
if exist "%TEMP%\clouddiag" (
    rmdir /S /Q "%TEMP%\clouddiag" >nul 2>&1
    echo   已删除 %TEMP%\clouddiag
)
echo.

REM ── 4. 结果 ──
echo [4/4] 检查残留...
set "LEFT=0"
for %%D in (%DIRS%) do (
    for %%F in (clouddiag-bridge-win64.exe clouddiag-bridge.exe bridge.exe) do (
        if exist "%%D\%%F" (
            echo   [!] 仍存在: %%D\%%F（可能被占用，请关闭后重试）
            set "LEFT=1"
        )
    )
)
if "!LEFT!"=="0" (
    echo   未发现残留文件
)

echo.
echo ==============================================
if "!FOUND!"=="1" (
    echo  桥接器已卸载
) else (
    echo  未发现本程序的文件（可能已卸载）
)
echo ==============================================
echo  说明: 本脚本只删除本程序自身的文件与日志，未改动系统其它配置。
echo.
pause
