//go:build windows

package main

import (
	"os/exec"
	"strconv"
)

// killProcess 终止命令进程（含子进程树）— Windows: taskkill /T /F
func killProcess(cmd *exec.Cmd) error {
	if cmd == nil || cmd.Process == nil {
		return nil
	}
	kill := exec.Command("taskkill", "/F", "/T", "/PID", strconv.Itoa(cmd.Process.Pid))
	return kill.Run()
}
