//go:build windows

package main

// 原生屏幕截图（GDI BitBlt）——2026-11-02
// 抓屏只能由桥接器自己做：Defender 用签名 HackTool:PowerShell/EmpireGetScreenshot.C
// 误杀一切 PowerShell + CopyFromScreen 的脚本（客户机不让加白名单）。
//
// 2026-11-02 追加：默认只抓【主显示器】。
//   实测双屏客户机抓整块虚拟桌面（3840×1080）→ 第二块屏是黑的，画面变成 3.56:1 超宽条，
//   右侧一大片黑。默认主屏 = 16:9 正常画面；需要整屏时传 monitor="all"。

import (
	"fmt"
	"image"
	"syscall"
	"unsafe"
)

var (
	modUser32 = syscall.NewLazyDLL("user32.dll")
	modGdi32  = syscall.NewLazyDLL("gdi32.dll")

	procSetProcessDPIAware     = modUser32.NewProc("SetProcessDPIAware")
	procGetDC                  = modUser32.NewProc("GetDC")
	procReleaseDC              = modUser32.NewProc("ReleaseDC")
	procGetSystemMetrics       = modUser32.NewProc("GetSystemMetrics")
	procEnumDisplayMonitors    = modUser32.NewProc("EnumDisplayMonitors")
	procGetMonitorInfoW        = modUser32.NewProc("GetMonitorInfoW")
	procCreateCompatibleDC     = modGdi32.NewProc("CreateCompatibleDC")
	procCreateCompatibleBitmap = modGdi32.NewProc("CreateCompatibleBitmap")
	procSelectObject           = modGdi32.NewProc("SelectObject")
	procBitBlt                 = modGdi32.NewProc("BitBlt")
	procGetDIBits              = modGdi32.NewProc("GetDIBits")
	procDeleteObject           = modGdi32.NewProc("DeleteObject")
	procDeleteDC               = modGdi32.NewProc("DeleteDC")
)

const (
	smXVirtualScreen       = 76
	smYVirtualScreen       = 77
	smCXVirtualScreen      = 78
	smCYVirtualScreen      = 79
	smCMonitors            = 80
	srcCopy                = 0x00CC0020
	captureBLT             = 0x40000000
	dibRGBColors           = 0
	monitorInfoFPrimary    = 0x00000001
)

type rect32 struct{ Left, Top, Right, Bottom int32 }

type monitorInfoEx struct {
	cbSize    uint32
	rcMonitor rect32
	rcWork    rect32
	dwFlags   uint32
	szDevice  [32]uint16
}

type bitmapInfoHeader struct {
	biSize          uint32
	biWidth         int32
	biHeight        int32
	biPlanes        uint16
	biBitCount      uint16
	biCompression   uint32
	biSizeImage     uint32
	biXPelsPerMeter int32
	biYPelsPerMeter int32
	biClrUsed       uint32
	biClrImportant  uint32
}

type bitmapInfo struct {
	bmiHeader bitmapInfoHeader
	bmiColors [3]uint32
}

// supportsScreenshot 本平台是否支持原生截图
func supportsScreenshot() bool { return true }

func getSys(idx int) int {
	r, _, _ := procGetSystemMetrics.Call(uintptr(idx))
	return int(int32(r))
}

// primaryMonitorRect 枚举显示器，返回主显示器在虚拟桌面里的矩形
func primaryMonitorRect() (rect32, bool) {
	var found rect32
	ok := false
	cb := syscall.NewCallback(func(hMon, _hdc, _lprc, _data uintptr) uintptr {
		mi := monitorInfoEx{}
		mi.cbSize = uint32(unsafe.Sizeof(mi))
		r, _, _ := procGetMonitorInfoW.Call(hMon, uintptr(unsafe.Pointer(&mi)))
		if r != 0 && mi.dwFlags&monitorInfoFPrimary != 0 {
			found = mi.rcMonitor
			ok = true
			return 0 // 找到主屏即停止枚举
		}
		return 1
	})
	procEnumDisplayMonitors.Call(0, 0, cb, 0)
	return found, ok
}

// captureRect 抓指定屏幕矩形
func captureRect(x, y, w, h int) (image.Image, error) {
	if w <= 0 || h <= 0 {
		return nil, fmt.Errorf("抓屏区域无效：%dx%d", w, h)
	}
	hdcScreen, _, dcErr := procGetDC.Call(0)
	if hdcScreen == 0 {
		return nil, fmt.Errorf("GetDC 失败：%v", dcErr)
	}
	defer procReleaseDC.Call(0, hdcScreen)

	hdcMem, _, memErr := procCreateCompatibleDC.Call(hdcScreen)
	if hdcMem == 0 {
		return nil, fmt.Errorf("CreateCompatibleDC 失败：%v", memErr)
	}
	defer procDeleteDC.Call(hdcMem)

	hbm, _, bmErr := procCreateCompatibleBitmap.Call(hdcScreen, uintptr(w), uintptr(h))
	if hbm == 0 {
		return nil, fmt.Errorf("CreateCompatibleBitmap 失败：%v", bmErr)
	}
	defer procDeleteObject.Call(hbm)

	oldObj, _, _ := procSelectObject.Call(hdcMem, hbm)
	ok, _, bltErr := procBitBlt.Call(hdcMem, 0, 0, uintptr(w), uintptr(h),
		hdcScreen, uintptr(int32(x)), uintptr(int32(y)), uintptr(srcCopy|captureBLT))
	procSelectObject.Call(hdcMem, oldObj)
	if ok == 0 {
		return nil, fmt.Errorf("BitBlt 失败：%v（可能处于锁屏/安全桌面）", bltErr)
	}

	bi := bitmapInfo{}
	bi.bmiHeader.biSize = uint32(unsafe.Sizeof(bi.bmiHeader))
	bi.bmiHeader.biWidth = int32(w)
	bi.bmiHeader.biHeight = -int32(h) // 负数 = 自上而下
	bi.bmiHeader.biPlanes = 1
	bi.bmiHeader.biBitCount = 32
	bi.bmiHeader.biCompression = 0 // BI_RGB

	buf := make([]byte, w*h*4)
	lines, _, dibErr := procGetDIBits.Call(hdcMem, hbm, 0, uintptr(h),
		uintptr(unsafe.Pointer(&buf[0])), uintptr(unsafe.Pointer(&bi)), uintptr(dibRGBColors))
	if lines == 0 {
		return nil, fmt.Errorf("GetDIBits 失败：%v", dibErr)
	}
	rgba := image.NewRGBA(image.Rect(0, 0, w, h))
	for i := 0; i < len(buf); i += 4 {
		rgba.Pix[i] = buf[i+2]
		rgba.Pix[i+1] = buf[i+1]
		rgba.Pix[i+2] = buf[i]
		rgba.Pix[i+3] = 255
	}
	return rgba, nil
}

// captureScreenNative 抓屏：monitor="all" 抓整个虚拟桌面，其余（默认）只抓主显示器
func captureScreenNative(monitor string) (img image.Image, width, height, monitors int, err error) {
	// DPI 感知：不声明的话 150% 缩放下只能拿逻辑像素，4K 屏会缺块
	procSetProcessDPIAware.Call()
	monitors = getSys(smCMonitors)

	if monitor == "all" {
		x := getSys(smXVirtualScreen)
		y := getSys(smYVirtualScreen)
		width = getSys(smCXVirtualScreen)
		height = getSys(smCYVirtualScreen)
		if width <= 0 || height <= 0 {
			return nil, 0, 0, 0, fmt.Errorf("桌面尺寸为 0（无交互桌面会话，或屏幕已关闭/远程桌面已断开）")
		}
		im, e := captureRect(x, y, width, height)
		return im, width, height, monitors, e
	}

	r, ok := primaryMonitorRect()
	if !ok {
		// 枚举失败兜底：退回虚拟桌面
		x := getSys(smXVirtualScreen)
		y := getSys(smYVirtualScreen)
		width = getSys(smCXVirtualScreen)
		height = getSys(smCYVirtualScreen)
		if width <= 0 || height <= 0 {
			return nil, 0, 0, 0, fmt.Errorf("桌面尺寸为 0（无交互桌面会话，或屏幕已关闭/远程桌面已断开）")
		}
		im, e := captureRect(x, y, width, height)
		return im, width, height, monitors, e
	}
	width = int(r.Right - r.Left)
	height = int(r.Bottom - r.Top)
	im, e := captureRect(int(r.Left), int(r.Top), width, height)
	return im, width, height, monitors, e
}
