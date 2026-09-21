package main

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// AuditLogger 本地审计日志：记录连接状态与每一条执行过的命令。
// 路径: ~/.clouddiag/bridge.log （透明可审计，用户可随时查看）
type AuditLogger struct {
	mu   sync.Mutex
	file *os.File
}

func NewAuditLogger() *AuditLogger {
	home, err := os.UserHomeDir()
	if err != nil {
		home = "."
	}
	dir := filepath.Join(home, ".clouddiag")
	_ = os.MkdirAll(dir, 0o755)
	f, err := os.OpenFile(filepath.Join(dir, "bridge.log"),
		os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		// 写不了文件就不写，不阻塞主流程
		return &AuditLogger{}
	}
	return &AuditLogger{file: f}
}

func (l *AuditLogger) write(level, format string, args ...interface{}) {
	if l == nil {
		return
	}
	line := fmt.Sprintf("%s [%s] %s\n",
		time.Now().Format("2006-01-02 15:04:05"), level, fmt.Sprintf(format, args...))
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.file != nil {
		_, _ = l.file.WriteString(line)
	}
	// 同时打印到控制台（透明可见）
	fmt.Print(line)
}

func (l *AuditLogger) Info(format string, args ...interface{}) {
	l.write("INFO", format, args...)
}

func (l *AuditLogger) Warn(format string, args ...interface{}) {
	l.write("WARN", format, args...)
}

func (l *AuditLogger) Error(format string, args ...interface{}) {
	l.write("ERROR", format, args...)
}

// Command 记录一次命令执行（审计核心）
func (l *AuditLogger) Command(cmd string, shell string, exitCode int, outputBrief string) {
	l.write("CMD", "shell=%s exit=%d cmd=%q → %s", shell, exitCode, cmd, outputBrief)
}

// Close 关闭日志文件
func (l *AuditLogger) Close() {
	if l != nil && l.file != nil {
		_ = l.file.Close()
	}
}
