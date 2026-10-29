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

// 客户机文件上传到服务器 → 转 IDG 日志分析
//
// 2026-10-19 改造（线上实测驱动的修复）：
//   客户机 → 服务器 单次 14.75MB multipart 连续失败：
//     · PS1 版桥接器：curl exit 56（receiving 数据失败）
//     · Go 版桥接器：remote error: tls: bad record MAC（TLS 记录损坏）
//   服务器侧自测（15MB × 4 次，443 / 8443 / 强制 HTTP1.1）全部正常 →
//   问题在客户机到服务器这段链路（MTU 不匹配 / 杀软 HTTPS 扫描 / 中间设备）。
//
//   两条对策：
//     ① 分块上传：1MB 一块，坏一块只重传该块（不再整包重来），每块最多重试 4 次
//     ② 地址降级：按服务器下发的候选地址依次尝试（https 主 → https:8443 → 明文 http）
//        候选地址由服务端下发（upload_bases），客户端不硬编码域名/端口；
//        明文兜底由服务端开关控制（UPLOAD_ALLOW_PLAIN_HTTP=1 才下发）
//
// 协议：
//   服务器 → bridge: {"type":"file_upload_request","id":"up_x","path":"C:\\...\\a.7z",
//                     "upload_bases":["https://host","https://host:8443"]}
//   bridge → 服务器:
//     POST {base}/api/bridge/upload/chunk?room=&token=&fid=&seq=   (multipart: file)
//     POST {base}/api/bridge/upload/commit?room=&token=&fid=&name=
//   小文件（≤3MB）先试单次 /api/bridge/upload，失败自动改分块

const (
	uploadChunkSize  = 1 << 20 // 1 MiB（上传分块，区别于 file.go 里 WS 下载用的 chunkSize）
	chunkThreshold   = 3 << 20 // ≤3MB 先走单次
	chunkMaxAttempts = 4       // 单块最多尝试
)

// FileUploadReqSpec 服务器请求的上传
type FileUploadReqSpec struct {
	ID          string   `json:"id"`
	Path        string   `json:"path"`
	UploadBases []string `json:"upload_bases"`
}

// uploadBases 候选地址：优先用服务器下发的，其次由 WS 地址推导（兼容老服务端）
func (c *Client) uploadBases(spec FileUploadReqSpec) []string {
	if len(spec.UploadBases) > 0 {
		out := make([]string, 0, len(spec.UploadBases))
		for _, b := range spec.UploadBases {
			b = strings.TrimRight(strings.TrimSpace(b), "/")
			if b != "" {
				out = append(out, b)
			}
		}
		if len(out) > 0 {
			return out
		}
	}
	base := strings.Replace(c.cfg.ServerURL, "wss://", "https://", 1)
	base = strings.Replace(base, "ws://", "http://", 1)
	base = strings.TrimRight(base, "/")
	if i := strings.Index(base, "/ws"); i > 0 {
		base = base[:i]
	}
	return []string{base}
}

// handleUploadRequest 上传本机文件 → 服务器（分块 + 多地址降级）
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
	size := fi.Size()
	name := filepath.Base(spec.Path)
	bases := c.uploadBases(spec)
	c.cfg.Logger.Info("上传 %s（%s），候选地址 %d 个", name, humanSize(size), len(bases))

	var lastErr error
	for _, base := range bases {
		c.cfg.Logger.Info("尝试上传地址: %s", base)
		var jobID string
		if size <= chunkThreshold {
			jobID, lastErr = c.uploadSingle(base, f, spec, name)
			if lastErr != nil {
				c.cfg.Logger.Warn("单次上传失败（%v），改走分块", lastErr)
				if _, e := f.Seek(0, io.SeekStart); e != nil {
					fail(e.Error())
					return nil
				}
			}
		}
		if jobID == "" {
			jobID, lastErr = c.uploadChunked(base, f, spec, name, size)
		}
		if jobID != "" {
			c.cfg.Logger.Info("上传成功: %s (%d bytes) -> job=%s", name, size, jobID)
			c.mu.Lock()
			conn := c.conn
			c.mu.Unlock()
			if conn != nil {
				body, _ := json.Marshal(map[string]interface{}{
					"ok": true, "job_id": jobID,
					"analyze_url": "/log-analyzer/analyze/" + jobID,
				})
				c.send(conn, map[string]interface{}{
					"type": "file_upload_result",
					"id":   spec.ID,
					"path": spec.Path,
					"body": string(body),
				})
			}
			return nil
		}
		if _, e := f.Seek(0, io.SeekStart); e != nil {
			fail(e.Error())
			return nil
		}
	}
	fail(describeUploadErr(lastErr))
	return nil
}

// uploadSingle 单次 multipart（小文件优先）
func (c *Client) uploadSingle(base string, f *os.File, spec FileUploadReqSpec, name string) (string, error) {
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
	upURL := fmt.Sprintf("%s/api/bridge/upload?room=%s&token=%s&fid=%s",
		base, url.QueryEscape(c.cfg.RoomCode), url.QueryEscape(c.cfg.Token), url.QueryEscape(spec.ID))
	req, err := http.NewRequest("POST", upURL, pr)
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", mw.FormDataContentType())
	client := &http.Client{Timeout: 900 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 64*1024))
	if resp.StatusCode != 200 {
		return "", fmt.Errorf("http %d: %s", resp.StatusCode, string(body))
	}
	return parseJobID(body)
}

// uploadChunked 1MB 分块上传 + 坏块重试 + commit
func (c *Client) uploadChunked(base string, f *os.File, spec FileUploadReqSpec, name string, size int64) (string, error) {
	total := (size + uploadChunkSize - 1) / uploadChunkSize
	buf := make([]byte, uploadChunkSize)
	var uploaded int64
	for seq := int64(0); seq < total; seq++ {
		n, rerr := io.ReadFull(f, buf)
		if rerr != nil && rerr != io.ErrUnexpectedEOF && rerr != io.EOF {
			return "", rerr
		}
		var lastErr error
		for attempt := 1; attempt <= chunkMaxAttempts; attempt++ {
			lastErr = c.postChunk(base, spec, seq, buf[:n])
			if lastErr == nil {
				break
			}
			c.cfg.Logger.Warn("分块 %d/%d 第 %d 次失败: %v", seq+1, total, attempt, lastErr)
			time.Sleep(time.Duration(attempt) * time.Second)
		}
		if lastErr != nil {
			return "", fmt.Errorf("分块 %d/%d 失败: %v", seq+1, total, lastErr)
		}
		uploaded += int64(n)
		if seq%20 == 0 || seq == total-1 {
			c.cfg.Logger.Info("上传进度 %d/%d 块（%s / %s）", seq+1, total, humanSize(uploaded), humanSize(size))
		}
	}
	commitURL := fmt.Sprintf("%s/api/bridge/upload/commit?room=%s&token=%s&fid=%s&name=%s",
		base, url.QueryEscape(c.cfg.RoomCode), url.QueryEscape(c.cfg.Token),
		url.QueryEscape(spec.ID), url.QueryEscape(name))
	client := &http.Client{Timeout: 900 * time.Second}
	resp, err := client.Post(commitURL, "application/json", nil)
	if err != nil {
		return "", fmt.Errorf("commit 失败: %w", err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 64*1024))
	if resp.StatusCode != 200 {
		return "", fmt.Errorf("commit http %d: %s", resp.StatusCode, string(body))
	}
	return parseJobID(body)
}

func (c *Client) postChunk(base string, spec FileUploadReqSpec, seq int64, chunk []byte) error {
	pr, pw := io.Pipe()
	mw := multipart.NewWriter(pw)
	go func() {
		fw, err := mw.CreateFormFile("file", "chunk.bin")
		if err == nil {
			_, err = fw.Write(chunk)
		}
		if err != nil {
			pw.CloseWithError(err)
			return
		}
		mw.Close()
		pw.Close()
	}()
	u := fmt.Sprintf("%s/api/bridge/upload/chunk?room=%s&token=%s&fid=%s&seq=%d",
		base, url.QueryEscape(c.cfg.RoomCode), url.QueryEscape(c.cfg.Token),
		url.QueryEscape(spec.ID), seq)
	req, err := http.NewRequest("POST", u, pr)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", mw.FormDataContentType())
	client := &http.Client{Timeout: 180 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 8192))
	if resp.StatusCode != 200 {
		return fmt.Errorf("http %d: %s", resp.StatusCode, string(body))
	}
	return nil
}

func parseJobID(body []byte) (string, error) {
	var out struct {
		JobID string `json:"job_id"`
		Error string `json:"error"`
	}
	if err := json.Unmarshal(body, &out); err != nil {
		return "", fmt.Errorf("响应解析失败: %s", string(body))
	}
	if out.JobID == "" {
		if out.Error != "" {
			return "", fmt.Errorf("%s", out.Error)
		}
		return "", fmt.Errorf("响应缺少 job_id: %s", string(body))
	}
	return out.JobID, nil
}

func humanSize(n int64) string {
	const unit = 1024
	if n < unit {
		return fmt.Sprintf("%d B", n)
	}
	div, exp := int64(unit), 0
	for m := n / unit; m >= unit; m /= unit {
		div *= unit
		exp++
	}
	return fmt.Sprintf("%.2f %cB", float64(n)/float64(div), "KMGTPE"[exp])
}

func describeUploadErr(err error) string {
	if err == nil {
		return "上传失败（未知原因）"
	}
	s := err.Error()
	switch {
	case strings.Contains(s, "bad record MAC"):
		return "上传失败：链路 TLS 记录损坏（MTU 不匹配 / 杀软 HTTPS 扫描 / 中间设备），分块与换端口均已尝试仍失败"
	case strings.Contains(s, "connection reset"), strings.Contains(s, "broken pipe"):
		return "上传失败：连接被中途重置（客户机上行网络不稳）：" + s
	case strings.Contains(s, "timeout"), strings.Contains(s, "deadline exceeded"):
		return "上传失败：传输超时（客户机上行太慢）：" + s
	case strings.Contains(s, "no such host"), strings.Contains(s, "lookup"):
		return "上传失败：域名解析失败（客户机 DNS 异常）：" + s
	}
	return "上传失败：" + s
}
