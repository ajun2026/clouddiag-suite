package main

import (
	"encoding/base64"
	"os"
	"path/filepath"
)

// 文件通道（v2 管道化）
//  - file_download: 服务器请求 bridge 上传本机文件（如诊断日志包）
//  - file_upload:   服务器推送文件到 bridge（如修复脚本、工具），分块传输
//
// 协议消息：
//   服务器 → bridge:
//     {"type":"file_download","id":"...","path":"C:\\...\\report.zip"}
//     {"type":"file_upload","id":"...","path":"C:\\...\\target","data":"<base64>","chunk":0,"total":3,"name":"tool.ps1"}
//   bridge → 服务器:
//     {"type":"file_download_result","id":"...","path":"...","name":"...","data":"<base64>","size":N}
//     {"type":"file_download_error","id":"...","error":"..."}
//     {"type":"file_upload_result","id":"...","path":"...","size":N}

// chunkSize 单块 base64 载荷上限（256KB 原文 ≈ 341KB base64，WebSocket 消息可承受）
const chunkSize = 256 * 1024

// FileDownloadSpec 服务器请求的文件下载
type FileDownloadSpec struct {
	ID   string `json:"id"`
	Path string `json:"path"`
}

// FileUploadSpec 服务器推送的文件块
type FileUploadSpec struct {
	ID    string `json:"id"`
	Path  string `json:"path"`
	Name  string `json:"name"`
	Data  string `json:"data"` // base64
	Chunk int    `json:"chunk"`
	Total int    `json:"total"`
}

// readFileChunked 读取文件并按块返回 base64 载荷列表
func readFileChunked(path string) ([]string, int, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, 0, err
	}
	raw := []byte(data)
	var chunks []string
	for off := 0; off < len(raw); off += chunkSize {
		end := off + chunkSize
		if end > len(raw) {
			end = len(raw)
		}
		chunks = append(chunks, base64.StdEncoding.EncodeToString(raw[off:end]))
	}
	return chunks, len(raw), nil
}

// safeJoinPath 防止路径逃逸：只允许绝对路径下的合法文件
func safeJoinPath(base, name string) string {
	return filepath.Join(base, filepath.Base(name))
}
