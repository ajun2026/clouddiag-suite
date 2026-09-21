package main

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	urlpkg "net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

// Client WebSocket 客户端：连接、心跳、重连、消息分发
type Client struct {
	cfg    *Config
	conn   *websocket.Conn
	mu     sync.Mutex // 保护 conn 写入
	stop   chan struct{}
	closed bool
}

func NewClient(cfg *Config) *Client {
	return &Client{cfg: cfg, stop: make(chan struct{})}
}

// Run 阻塞运行，内部自动重连
func (c *Client) Run() {
	backoff := 3 * time.Second
	attempt := 0
	for {
		if c.closed {
			return
		}
		attempt++
		err := c.connectAndServe()
		if c.closed {
			return
		}
		c.cfg.Logger.Warn("连接断开 (第 %d 次): %v，%s 后重连…", attempt, err, backoff)
		select {
		case <-c.stop:
			return
		case <-time.After(backoff):
		}
		if backoff < 30*time.Second {
			backoff *= 2
		}
	}
}

// Shutdown 优雅关闭
func (c *Client) Shutdown() {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return
	}
	c.closed = true
	close(c.stop)
	if c.conn != nil {
		_ = c.conn.WriteControl(websocket.CloseMessage,
			websocket.FormatCloseMessage(websocket.CloseNormalClosure, "bridge shutdown"), time.Now().Add(2*time.Second))
		_ = c.conn.Close()
	}
	c.cfg.Logger.Info("bridge 已退出，审计日志见 ~/.clouddiag/bridge.log")
}

// connectAndServe 建立连接并进入消息循环
func (c *Client) connectAndServe() error {
	url := fmt.Sprintf("%s/ws/bridge/%s", c.cfg.ServerURL, c.cfg.RoomCode)
	if c.cfg.Token != "" {
		url += "?token=" + urlpkg.QueryEscape(c.cfg.Token)
	}
	c.cfg.Logger.Info("连接服务器 %s (房间 %s)…", url, c.cfg.RoomCode)

	dialer := websocket.Dialer{
		HandshakeTimeout: 15 * time.Second,
	}
	conn, resp, err := dialer.Dial(url, nil)
	if err != nil {
		if resp != nil {
			return fmt.Errorf("HTTP %s: %v", resp.Status, err)
		}
		return err
	}
	c.mu.Lock()
	c.conn = conn
	c.mu.Unlock()
	defer func() {
		c.mu.Lock()
		c.conn = nil
		c.mu.Unlock()
		_ = conn.Close()
	}()

	c.cfg.Logger.Info("已连接房间 %s", c.cfg.RoomCode)

	// 立即上报身份
	c.sendIdentify()

	// 心跳 goroutine
	stopHeartbeat := make(chan struct{})
	defer close(stopHeartbeat)
	go c.heartbeatLoop(conn, stopHeartbeat)

	// 读循环
	conn.SetReadDeadline(time.Now().Add(75 * time.Second))
	for {
		_, raw, err := conn.ReadMessage()
		if err != nil {
			// 区分断开原因，便于诊断
			if websocket.IsCloseError(err, websocket.CloseNormalClosure, websocket.CloseGoingAway) {
				c.cfg.Logger.Warn("连接被服务器正常关闭: %v", err)
			} else if netErr, ok := err.(net.Error); ok && netErr.Timeout() {
				c.cfg.Logger.Warn("读超时 (%s): 75s 内未收到服务器消息（心跳/命令响应），连接断开", time.Now().Format("15:04:05"))
			} else {
				c.cfg.Logger.Warn("连接异常断开: %v", err)
			}
			return err
		}
		conn.SetReadDeadline(time.Now().Add(75 * time.Second))
		var msg map[string]interface{}
		if err := json.Unmarshal(raw, &msg); err != nil {
			c.cfg.Logger.Warn("收到无法解析的消息: %s", brief(string(raw), 200))
			continue
		}
		if err := c.dispatch(msg); err != nil {
			c.cfg.Logger.Warn("处理消息出错: %v", err)
		}
	}
}

// heartbeatLoop 每 25s 发一次心跳
func (c *Client) heartbeatLoop(conn *websocket.Conn, stop chan struct{}) {
	t := time.NewTicker(25 * time.Second)
	defer t.Stop()
	for {
		select {
		case <-stop:
			return
		case <-t.C:
			c.send(conn, map[string]interface{}{"type": "heartbeat", "ts": time.Now().Unix()})
		}
	}
}

// sendIdentify 上报本机身份
func (c *Client) sendIdentify() {
	c.mu.Lock()
	conn := c.conn
	c.mu.Unlock()
	if conn == nil {
		return
	}
	c.send(conn, map[string]interface{}{
		"type": "identify",
		"info": c.cfg.Info,
	})
}

// dispatch 分发服务器消息
func (c *Client) dispatch(msg map[string]interface{}) error {
	typ, _ := msg["type"].(string)
	switch typ {
	case "identify_request":
		c.sendIdentify()

	case "ping":
		c.mu.Lock()
		conn := c.conn
		c.mu.Unlock()
		if conn != nil {
			c.send(conn, map[string]interface{}{"type": "pong"})
		}

	case "pong":
		// 服务器对 heartbeat 的回复，静默处理（仅用于重置读超时）

	case "status":
		// 服务器状态/心跳消息（连接状态、房间状态等）——静默忽略，不影响功能

	case "error":
		c.cfg.Logger.Info("server error: %v", msg["content"])

	case "command":
		// 异步执行命令：命令可能耗时 60~90s，同步执行会阻塞读循环，
		// 导致心跳 pong 无人读 → 75s 读超时 → 连接被误断。
		// 改为 goroutine 执行，读循环立即返回继续收消息。
		go func() {
			if err := c.handleCommand(msg); err != nil {
				c.cfg.Logger.Warn("处理命令出错: %v", err)
			}
		}()
		return nil

	case "file_download":
		return c.handleFileDownload(msg)

	case "file_upload":
		return c.handleFileUpload(msg)

	case "file_upload_request":
		return c.handleUploadRequest(msg)

	case "close":
		c.cfg.Logger.Info("服务器要求断开: %v", msg["reason"])
		c.Shutdown()
		os.Exit(0)

	default:
		c.cfg.Logger.Info("收到未知消息类型: %s", typ)
	}
	return nil
}

// handleCommand 执行服务器下发的命令（管道核心）
func (c *Client) handleCommand(msg map[string]interface{}) error {
	b, _ := json.Marshal(msg)
	var spec CommandSpec
	if err := json.Unmarshal(b, &spec); err != nil {
		return err
	}
	c.cfg.Logger.Info("收到命令: %s", brief(spec.Command, 160))
	res := ExecuteCommand(spec, c.cfg.Logger)
	c.mu.Lock()
	conn := c.conn
	c.mu.Unlock()
	if conn != nil {
		c.send(conn, map[string]interface{}{
			"type":        "command_result",
			"id":          res.ID,
			"output":      res.Output,
			"exit_code":   res.ExitCode,
			"error":       res.Error,
			"duration_ms": res.Duration,
		})
	}
	return nil
}

// handleFileDownload 读取本机文件并分块上传
func (c *Client) handleFileDownload(msg map[string]interface{}) error {
	b, _ := json.Marshal(msg)
	var spec FileDownloadSpec
	if err := json.Unmarshal(b, &spec); err != nil {
		return err
	}
	c.cfg.Logger.Info("收到文件下载请求: %s", spec.Path)

	chunks, size, err := readFileChunked(spec.Path)
	if err != nil {
		c.cfg.Logger.Warn("文件读取失败 %s: %v", spec.Path, err)
		c.sendToServer(map[string]interface{}{
			"type":  "file_download_error",
			"id":    spec.ID,
			"error": err.Error(),
		})
		return nil
	}
	name := filepath.Base(spec.Path)
	for i, ch := range chunks {
		c.sendToServer(map[string]interface{}{
			"type":  "file_download_result",
			"id":    spec.ID,
			"path":  spec.Path,
			"name":  name,
			"data":  ch,
			"chunk": i,
			"total": len(chunks),
			"size":  size,
		})
	}
	c.cfg.Logger.Info("文件上传完成: %s (%d 块, %d bytes)", spec.Path, len(chunks), size)
	return nil
}

// handleFileUpload 接收服务器推送的文件块并写入
func (c *Client) handleFileUpload(msg map[string]interface{}) error {
	b, _ := json.Marshal(msg)
	var spec FileUploadSpec
	if err := json.Unmarshal(b, &spec); err != nil {
		return err
	}
	decoded, err := base64.StdEncoding.DecodeString(spec.Data)
	if err != nil {
		return err
	}
	// 防路径逃逸：仅使用文件名部分，落在默认下载目录
	dir := filepath.Join(os.TempDir(), "clouddiag")
	_ = os.MkdirAll(dir, 0o755)
	target := safeJoinPath(dir, spec.Name)
	f, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return err
	}
	if _, err := f.Write(decoded); err != nil {
		_ = f.Close()
		return err
	}
	_ = f.Close()
	c.cfg.Logger.Info("接收文件块 %d/%d → %s", spec.Chunk+1, spec.Total, target)

	// 最后一块时确认
	if spec.Chunk+1 >= spec.Total {
		c.sendToServer(map[string]interface{}{
			"type": "file_upload_result",
			"id":   spec.ID,
			"path": target,
		})
	}
	return nil
}

// sendToServer 线程安全的连接写（不存在则忽略）
func (c *Client) sendToServer(payload map[string]interface{}) {
	c.mu.Lock()
	conn := c.conn
	c.mu.Unlock()
	if conn != nil {
		c.send(conn, payload)
	}
}

// send 写入一条 JSON 消息
func (c *Client) send(conn *websocket.Conn, payload map[string]interface{}) {
	c.mu.Lock()
	defer c.mu.Unlock()
	_ = conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
	if err := conn.WriteJSON(payload); err != nil {
		c.cfg.Logger.Warn("发送失败: %v", err)
	}
}

// 保证 http 包被引用（gorilla Dialer 内部使用，这里显式声明依赖）
var _ = http.MethodGet

// 兼容性：避免 strings 未使用
var _ = strings.TrimSpace
