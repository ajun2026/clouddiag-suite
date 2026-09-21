package main

import (
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// 方案 A（2026-09-10 主人确认）：客户机文件上传到服务器 → 转 IDG 日志分析
// 不走 WS 分块——HTTP multipart 直传一次（几百 MB 也行——与 IDG 上传页同款）
//
// 协议：
//   服务器 → bridge: {"type":"file_upload_request","id":"up_xxx","path":"C:\\DiagLogs\\tslog\\x.7z"}
//   bridge → 服务器(HTTP): POST {httpBase}/api/bridge/upload?room=&token=&fid=  (multipart: file)
//   服务器 → bridge(HTTP 响应): {"ok":true,"job_id":"...","analyze_url":"..."}
//   bridge → 服务器(WS): {"type":"file_upload_result","id":"up_xxx","path":"...","body":"{...}"}

// FileUploadReqSpec 服务器请求的上传
type FileUploadReqSpec struct {
	ID   string `json:"id"`
	Path string `json:"path"`
}

// handleUploadRequest 读本机文件 → HTTP multipart 直传服务器
func (c *Client) handleUploadRequest(msg map[string]interface{}) error {
	b, _ := json.Marshal(msg)
	var spec FileUploadReqSpec
	if err := json.Unmarshal(b, &spec); err != nil {
		return err
	}
	c.cfg.Logger.Info("收到上传请求: %s", spec.Path)

	fail := func(msg string) {
		c.cfg.Logger.Warn("上传失败 %s: %s", spec.Path, msg)
		c.mu.Lock()
		conn := c.conn
		c.mu.Unlock()
		if conn != nil {
			c.send(conn, map[string]interface{}{
				"type":  "file_upload_error",
				"id":    spec.ID,
				"error": msg,
			})
		}
	}

	f, err := os.Open(spec.Path)
	if err != nil {
		fail("file not found: " + spec.Path)
		return nil
	}
	defer f.Close()
	fi, err := f.Stat()
	if err != nil {
		fail(err.Error())
		return nil
	}
	name := filepath.Base(spec.Path)

	// HTTP 地址推导（ws->http / wss->https）
	httpBase := strings.Replace(c.cfg.ServerURL, "wss://", "https://", 1)
	httpBase = strings.Replace(httpBase, "ws://", "http://", 1)
	httpBase = strings.TrimRight(httpBase, "/")
	upURL := fmt.Sprintf("%s/api/bridge/upload?room=%s&token=%s&fid=%s",
		httpBase, url.QueryEscape(c.cfg.RoomCode), url.QueryEscape(c.cfg.Token), url.QueryEscape(spec.ID))

	// 流式 multipart（io.Pipe——不整读内存）
	pr, pw := io.Pipe()
	mw := multipart.NewWriter(pw)
	go func() {
		fw, err := mw.CreateFormFile("file", name)
		if err == nil {
			_, err = io.Copy(fw, f)
		}
		if err != nil {
			pw.CloseWithError(err)
			return
		}
		mw.Close()
		pw.Close()
	}()

	req, err := http.NewRequest("POST", upURL, pr)
	if err != nil {
		fail(err.Error())
		return nil
	}
	req.Header.Set("Content-Type", mw.FormDataContentType())

	client := &http.Client{Timeout: 900 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		fail("http upload failed: " + err.Error())
		return nil
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 64*1024))

	if resp.StatusCode != 200 {
		fail(fmt.Sprintf("http %d: %s", resp.StatusCode, string(body)))
		return nil
	}
	c.cfg.Logger.Info("上传成功: %s (%d bytes) -> %s", name, fi.Size(), string(body))
	c.mu.Lock()
	conn := c.conn
	c.mu.Unlock()
	if conn != nil {
		c.send(conn, map[string]interface{}{
			"type": "file_upload_result",
			"id":   spec.ID,
			"path": spec.Path,
			"body": string(body),
		})
	}
	return nil
}
