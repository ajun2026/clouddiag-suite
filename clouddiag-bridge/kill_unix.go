//go:build !windows

package main

import (
	"os/exec"
	"syscall"
)

// killProcess 终止命令进程（含子进程树）— Linux/macOS: 向进程组发 SIGKILL
func killProcess(cmd *exec.Cmd) error {
	if cmd == nil || cmd.Process == nil {
		return nil
	}
	_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	return nil
}
