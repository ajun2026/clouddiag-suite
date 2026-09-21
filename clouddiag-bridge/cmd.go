package main

import (
	"context"
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"time"
)

// CommandSpec 服务器下发的命令请求
type CommandSpec struct {
	ID      string `json:"id"`
	Command string `json:"command"`
	Timeout int    `json:"timeout"` // 秒
	Cwd     string `json:"cwd"`
	Shell   string `json:"shell"` // auto | powershell | cmd | bash | sh
}

// CommandResult 命令执行结果
type CommandResult struct {
	ID       string `json:"id"`
	Output   string `json:"output"`
	ExitCode int    `json:"exit_code"`
	Error    string `json:"error,omitempty"`
	Duration int64  `json:"duration_ms"`
}

// ShellName 解析出当前平台实际使用的 shell 名称（用于审计展示）
func ShellName(spec CommandSpec) string {
	if spec.Shell != "" && spec.Shell != "auto" {
		return spec.Shell
	}
	if runtime.GOOS == "windows" {
		return "powershell"
	}
	return "bash"
}

// buildCommand 根据平台和 shell 参数构造 exec.Command
// Windows 上避免 powershell 的编码/引号陷阱：直接走 -NoProfile -NonInteractive -Command
func buildCommand(spec CommandSpec) *exec.Cmd {
	shell := strings.ToLower(spec.Shell)
	cmdStr := spec.Command

	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "windows":
		switch shell {
		case "cmd":
			cmd = exec.Command("cmd.exe", "/c", cmdStr)
		case "powershell", "pwsh":
			cmd = exec.Command("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmdStr)
		case "bash":
			// Windows 上也可能有 git-bash / WSL，尽力支持
			cmd = exec.Command("bash.exe", "-c", cmdStr)
		default: // auto
			// 默认用 PowerShell（诊断场景以 PS 为主）
			cmd = exec.Command("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmdStr)
		}
	default: // linux / darwin
		switch shell {
		case "sh":
			cmd = exec.Command("/bin/sh", "-c", cmdStr)
		case "powershell":
			cmd = exec.Command("pwsh", "-NoProfile", "-NonInteractive", "-Command", cmdStr)
		default: // auto / bash
			cmd = exec.Command("/bin/bash", "-c", cmdStr)
		}
	}
	return cmd
}

// ExecuteCommand 执行一条命令并返回结果（管道核心）
func ExecuteCommand(spec CommandSpec, logger *AuditLogger) CommandResult {
	start := time.Now()
	res := CommandResult{ID: spec.ID}

	timeout := spec.Timeout
	if timeout <= 0 {
		timeout = 60
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(timeout)*time.Second)
	defer cancel()

	cmd := buildCommand(spec)
	if spec.Cwd != "" {
		if st, err := os.Stat(spec.Cwd); err == nil && st.IsDir() {
			cmd.Dir = spec.Cwd
		}
	}

	var outBuf strings.Builder
	var errBuf strings.Builder
	cmd.Stdout = &outBuf
	cmd.Stderr = &errBuf

	err := cmd.Start()
	if err != nil {
		res.Error = "启动命令失败: " + err.Error()
		res.ExitCode = -1
		logger.Command(spec.Command, ShellName(spec), -1, res.Error)
		return res
	}

	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()

	select {
	case <-ctx.Done():
		// 超时：杀掉进程树
		_ = killProcess(cmd)
		<-done
		res.Error = fmtTimeoutMsg(timeout)
		res.ExitCode = -1
	case err := <-done:
		if err != nil {
			if ee, ok := err.(*exec.ExitError); ok {
				res.ExitCode = ee.ExitCode()
			} else {
				res.Error = err.Error()
			}
		} else {
			res.ExitCode = 0
		}
	}

	// 合并输出（stderr 也带回，诊断时常有信息打到 stderr）
	output := outBuf.String()
	if errBuf.Len() > 0 {
		if output != "" && !strings.HasSuffix(output, "\n") {
			output += "\n"
		}
		output += errBuf.String()
	}
	res.Output = output
	res.Duration = time.Since(start).Milliseconds()

	logger.Command(spec.Command, ShellName(spec), res.ExitCode, brief(res.Output, 120))
	return res
}

func fmtTimeoutMsg(sec int) string {
	return "[timeout] 命令执行超过 " + strconv.Itoa(sec) + " 秒，已终止"
}

// brief 截断长输出用于审计日志
func brief(s string, n int) string {
	s = strings.TrimSpace(s)
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}
