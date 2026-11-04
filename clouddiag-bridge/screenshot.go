package main

// 截图请求处理（协议层，平台无关）——2026-11-02
//
// 协议：服务器 → 桥接器 {"type":"screenshot","id":"...","preview":true,
//                        "max_width":1280,"quality":55}
//      桥接器 → 服务器 {"type":"screenshot_result","id":"...","ok":true,
//                       "path":"C:\\...\\nexpert-shot-XXX.jpg","format":"jpg",
//                       "width":1280,"height":720,"src_width":3840,"src_height":2160,
//                       "bytes":78901,"monitors":2,"ms":47}
//
// 编码在客户机完成：
//   · 高清截图 → PNG（无损）
//   · 远程观察 → 缩放 + JPEG（体积小，1 fps 才跑得动），服务器不再需要图像库

import (
	"bytes"
	"fmt"
	"image"
	"image/jpeg"
	"image/png"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// screenshotCaps 上报给服务器本机支持的扩展能力
func screenshotCaps() []string {
	if supportsScreenshot() {
		return []string{"screenshot"}
	}
	return []string{}
}

// shotDir 截图落盘目录（与脚本推送目录一致，便于排查）
func shotDir() string { return filepath.Join(os.TempDir(), "clouddiag") }

// cleanupShots 控制临时截图目录体积。
//
// 2026-11-04 修复：原来只清理 "nexpert-shot-" 前缀，而实时观察帧的名字是
// "nexpert-preview-"，于是每 2 秒一帧、每帧约 110KB 的观察帧从来不会被删——
// 一小时 ~200MB、一天 ~4.9GB，全堆在客户机 %TEMP%\clouddiag 里。
// 现在的口径：
//   - 观察帧（preview）：只保留最新 3 帧（≈6 秒），其余立刻删；
//   - 高清截图（shot）：保留 24 小时，方便服务器回传或人工复查。
func cleanupShots(dir string) {
	ents, err := os.ReadDir(dir)
	if err != nil {
		return
	}
	type item struct {
		name string
		mod  time.Time
	}
	var previews, shots []item
	for _, e := range ents {
		if e.IsDir() {
			continue
		}
		n := e.Name()
		if !strings.HasPrefix(n, "nexpert-") {
			continue
		}
		info, err := e.Info()
		if err != nil {
			continue
		}
		switch {
		case strings.HasPrefix(n, "nexpert-preview-"):
			previews = append(previews, item{n, info.ModTime()})
		case strings.HasPrefix(n, "nexpert-shot-"):
			shots = append(shots, item{n, info.ModTime()})
		}
	}
	// 观察帧：新的在前，保留 3 个
	sort.Slice(previews, func(i, j int) bool { return previews[i].mod.After(previews[j].mod) })
	for i, p := range previews {
		if i >= 3 {
			os.Remove(filepath.Join(dir, p.name))
		}
	}
	// 高清截图：超过 24 小时清掉
	cutoff := time.Now().Add(-24 * time.Hour)
	for _, s := range shots {
		if s.mod.Before(cutoff) {
			os.Remove(filepath.Join(dir, s.name))
		}
	}
}

// downscale 面积平均缩放（不引第三方库；4800×2700 → 1280 宽约 3~8ms）
func downscale(src image.Image, maxW int) image.Image {
	b := src.Bounds()
	sw, sh := b.Dx(), b.Dy()
	if maxW <= 0 || sw <= maxW {
		return src
	}
	dw := maxW
	dh := int(float64(sh) * float64(maxW) / float64(sw))
	if dh < 1 {
		dh = 1
	}
	dst := image.NewRGBA(image.Rect(0, 0, dw, dh))
	// 快路径：源图就是 *image.RGBA 时直接读 Pix，避免每像素 At() 的接口开销
	// （4K→1280 面积平均约 800 万次取样，走 At() 会到 200ms 级，这里压到个位数毫秒）
	if srgba, ok := src.(*image.RGBA); ok {
		sw4 := srgba.Stride
		for dy := 0; dy < dh; dy++ {
			y0 := dy * sh / dh
			y1 := (dy + 1) * sh / dh
			if y1 <= y0 {
				y1 = y0 + 1
			}
			for dx := 0; dx < dw; dx++ {
				x0 := dx * sw / dw
				x1 := (dx + 1) * sw / dw
				if x1 <= x0 {
					x1 = x0 + 1
				}
				var ar, ag, ab, n uint32
				for y := y0; y < y1; y++ {
					row := y * sw4
					for x := x0; x < x1; x++ {
						i := row + x*4
						ar += uint32(srgba.Pix[i])
						ag += uint32(srgba.Pix[i+1])
						ab += uint32(srgba.Pix[i+2])
						n++
					}
				}
				if n == 0 {
					n = 1
				}
				o := dst.PixOffset(dx, dy)
				dst.Pix[o] = uint8(ar / n)
				dst.Pix[o+1] = uint8(ag / n)
				dst.Pix[o+2] = uint8(ab / n)
				dst.Pix[o+3] = 255
			}
		}
		return dst
	}
	type px struct{ r, g, b uint32 }
	for dy := 0; dy < dh; dy++ {
		y0 := dy * sh / dh
		y1 := (dy + 1) * sh / dh
		if y1 <= y0 {
			y1 = y0 + 1
		}
		for dx := 0; dx < dw; dx++ {
			x0 := dx * sw / dw
			x1 := (dx + 1) * sw / dw
			if x1 <= x0 {
				x1 = x0 + 1
			}
			var acc px
			var n uint32
			for y := y0; y < y1; y++ {
				for x := x0; x < x1; x++ {
					r, g, bb, _ := src.At(b.Min.X+x, b.Min.Y+y).RGBA()
					acc.r += r >> 8
					acc.g += g >> 8
					acc.b += bb >> 8
					n++
				}
			}
			if n == 0 {
				n = 1
			}
			i := dst.PixOffset(dx, dy)
			dst.Pix[i] = uint8(acc.r / n)
			dst.Pix[i+1] = uint8(acc.g / n)
			dst.Pix[i+2] = uint8(acc.b / n)
			dst.Pix[i+3] = 255
		}
	}
	return dst
}

// handleScreenshot 处理服务器下发的截图请求
func (c *Client) handleScreenshot(msg map[string]interface{}) {
	id, _ := msg["id"].(string)
	preview, _ := msg["preview"].(bool)
	maxW := 0
	if v, ok := msg["max_width"].(float64); ok {
		maxW = int(v)
	}
	quality := 90
	if v, ok := msg["quality"].(float64); ok && v > 0 {
		quality = int(v)
	}

	started := time.Now()
	reply := map[string]interface{}{"type": "screenshot_result", "id": id}

	monitor, _ := msg["monitor"].(string)
	if monitor == "" {
		monitor = "primary" // 默认只抓主显示器（双屏时避免把黑屏的第二块也抓进来）
	}
	src, w, h, monitors, err := captureScreenNative(monitor)
	if err != nil {
		reply["ok"] = false
		reply["error"] = err.Error()
		c.sendNow(reply)
		c.cfg.Logger.Info("screenshot failed: %v", err)
		return
	}

	img := src
	format := "png"
	if preview {
		format = "jpg"
		if maxW <= 0 {
			maxW = 1280
		}
		img = downscale(src, maxW)
	}

	var out bytes.Buffer
	if format == "jpg" {
		if quality < 10 {
			quality = 10
		}
		if quality > 95 {
			quality = 95
		}
		if err := jpeg.Encode(&out, img, &jpeg.Options{Quality: quality}); err != nil {
			reply["ok"] = false
			reply["error"] = fmt.Sprintf("JPEG 编码失败：%v", err)
			c.sendNow(reply)
			return
		}
	} else {
		enc := png.Encoder{CompressionLevel: png.DefaultCompression}
		if err := enc.Encode(&out, img); err != nil {
			reply["ok"] = false
			reply["error"] = fmt.Sprintf("PNG 编码失败：%v", err)
			c.sendNow(reply)
			return
		}
	}

	dir := shotDir()
	if err := os.MkdirAll(dir, 0o755); err != nil {
		reply["ok"] = false
		reply["error"] = fmt.Sprintf("创建临时目录失败：%v", err)
		c.sendNow(reply)
		return
	}
	room := c.cfg.RoomCode
	if room == "" {
		room = "room"
	}
	tag := "shot"
	if preview {
		tag = "preview"
	}
	name := fmt.Sprintf("nexpert-%s-%s-%s.%s", tag, room, time.Now().Format("20060102-150405"), format)
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, out.Bytes(), 0o644); err != nil {
		reply["ok"] = false
		reply["error"] = fmt.Sprintf("写入截图文件失败：%v", err)
		c.sendNow(reply)
		return
	}
	go cleanupShots(dir)

	bb := img.Bounds()
	reply["ok"] = true
	reply["path"] = path
	reply["format"] = format
	reply["width"] = bb.Dx()
	reply["height"] = bb.Dy()
	reply["src_width"] = w
	reply["src_height"] = h
	reply["bytes"] = out.Len()
	reply["monitors"] = monitors
	reply["monitor"] = monitor
	reply["ms"] = time.Since(started).Milliseconds()
	c.sendNow(reply)
	c.cfg.Logger.Info("screenshot ok: %s %dx%d (%dx%d src) %d bytes %dms -> %s",
		format, bb.Dx(), bb.Dy(), w, h, out.Len(), time.Since(started).Milliseconds(), path)
}

// sendNow 向当前连接发一条消息（连接已断则丢弃）
func (c *Client) sendNow(m map[string]interface{}) {
	c.mu.Lock()
	conn := c.conn
	c.mu.Unlock()
	if conn != nil {
		c.send(conn, m)
	}
}
