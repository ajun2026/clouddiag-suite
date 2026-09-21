//go:build windows

package main

import (
	"fmt"
	"os"
	"strings"

	"golang.org/x/sys/windows"
)

// isAdmin 检查当前进程是否以管理员权限运行（基于 Windows Token Elevation，
// 比 whoami /groups 更可靠：直接查进程令牌的 elevated 标志）
func isAdmin() bool {
	token := windows.GetCurrentProcessToken()
	return token.IsElevated()
}

// elevateSelf 以管理员权限重启自身（UAC 提权）。
// 原理：ShellExecuteW + "runas" verb → 触发 UAC 弹窗 → 用户同意后以管理员启动新进程。
// 新进程会带上 --elevated 标志，避免再次提权（防递归）。
// 返回 nil 表示新进程已成功启动；调用方应立即 os.Exit(0)。
func elevateSelf(serverURL, roomCode, token string) error {
	exe, err := os.Executable()
	if err != nil {
		return fmt.Errorf("定位自身程序失败: %w", err)
	}

	// 构造提权后进程的命令行：原参数 + --elevated
	args := []string{"--elevated"}
	if serverURL != "" && serverURL != "ws://localhost:8000" {
		args = append(args, "--server", serverURL)
	}
	if roomCode != "" {
		args = append(args, "--room", roomCode)
	}
	if token != "" {
		args = append(args, "--token", token)
	}
	cmdline := fmt.Sprintf("%s %s", quoteArg(exe), strings.Join(args, " "))

	verb, _ := windows.UTF16PtrFromString("runas")
	file, _ := windows.UTF16PtrFromString(exe)
	params, _ := windows.UTF16PtrFromString(cmdline)
	dir, _ := windows.UTF16PtrFromString("")

	// SW_SHOWNORMAL: 提权后新进程显示新控制台窗口（与当前分离）
	err = windows.ShellExecute(0, verb, file, params, dir, windows.SW_SHOWNORMAL)
	if err != nil {
		// 用户取消 UAC 或提权失败
		return fmt.Errorf("UAC 提权失败: %w", err)
	}
	return nil
}

// quoteArg 给含空格路径加引号（Windows 命令行规则）
func quoteArg(s string) string {
	if strings.ContainsAny(s, " \t") {
		return `"` + s + `"`
	}
	return s
}
