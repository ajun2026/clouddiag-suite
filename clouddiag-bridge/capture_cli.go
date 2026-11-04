package main

// 抓屏助手模式（2026-11-02）
//
// 为什么要这个：PowerShell 版桥接器（bridge.ps1）在客户机上一跑，抓屏只能靠
// PowerShell + System.Drawing，被 Defender 签名 HackTool:PowerShell/EmpireGetScreenshot.C
// 拦死。让 PS 版桥接器把抓屏交给 Go 助手 exe 完成，既不用客户改安全策略，
// 也不用现场换桥接器（PS 版脚本是每次连接现拉的，改服务器模板即全量生效）。
//
// 用法：clouddiag-bridge-win64.exe -capture <输出文件> [-capture-monitor primary|all]
//        [-capture-format png|jpg] [-capture-max-width 1280] [-capture-quality 55]
// 输出：
//   CAPTURE_OK=<path>
//   W=1280
//   H=720
//   MON=1
//   BYTES=78901
//   FORMAT=jpg

import (
	"bytes"
	"fmt"
	"image/jpeg"
	"image/png"
	"os"
	"path/filepath"
)

// runCaptureHelper 执行一次抓屏并写文件，返回进程退出码
func runCaptureHelper(path, monitor, format string, maxWidth, quality int) int {
	if path == "" {
		fmt.Println("CAPTURE_FAIL=未指定输出路径")
		return 2
	}
	img, w, h, monitors, err := captureScreenNative(monitor)
	if err != nil {
		fmt.Printf("CAPTURE_FAIL=%s\n", err.Error())
		return 2
	}

	out := img
	if format == "jpg" {
		if maxWidth > 0 {
			out = downscale(img, maxWidth)
		}
		if quality < 10 {
			quality = 10
		}
		if quality > 95 {
			quality = 95
		}
	} else {
		format = "png"
	}

	var buf bytes.Buffer
	if format == "jpg" {
		if e := jpeg.Encode(&buf, out, &jpeg.Options{Quality: quality}); e != nil {
			fmt.Printf("CAPTURE_FAIL=JPEG 编码失败：%v\n", e)
			return 2
		}
	} else {
		enc := png.Encoder{CompressionLevel: png.DefaultCompression}
		if e := enc.Encode(&buf, out); e != nil {
			fmt.Printf("CAPTURE_FAIL=PNG 编码失败：%v\n", e)
			return 2
		}
	}

	if dir := filepath.Dir(path); dir != "" {
		os.MkdirAll(dir, 0o755)
	}
	if e := os.WriteFile(path, buf.Bytes(), 0o644); e != nil {
		fmt.Printf("CAPTURE_FAIL=写入失败：%v\n", e)
		return 2
	}

	bb := out.Bounds()
	fmt.Printf("CAPTURE_OK=%s\n", path)
	fmt.Printf("W=%d\nH=%d\nMON=%d\nBYTES=%d\nFORMAT=%s\n", bb.Dx(), bb.Dy(), monitors, buf.Len(), format)
	_ = w
	_ = h
	return 0
}
