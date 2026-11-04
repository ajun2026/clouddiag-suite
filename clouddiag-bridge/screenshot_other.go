//go:build !windows

package main

import (
	"errors"
	"image"
)

// 非 Windows 平台：服务端仍用 shell 抓屏工具（gnome-screenshot / scrot / import）路径，
// 桥接器不上报该能力 → 服务端自动回退，行为与改动前一致。
func supportsScreenshot() bool { return false }

func captureScreenNative(monitor string) (image.Image, int, int, int, error) {
	return nil, 0, 0, 0, errors.New("该平台不支持桥接器原生截图")
}
