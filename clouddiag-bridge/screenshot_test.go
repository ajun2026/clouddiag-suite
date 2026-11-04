package main

import (
	"image"
	"image/color"
	"testing"
)

// 面积平均缩放的正确性：纯色块缩放后颜色必须保持不变（不能偏暗/偏亮）
func TestDownscaleSolidColor(t *testing.T) {
	src := image.NewRGBA(image.Rect(0, 0, 400, 300))
	for y := 0; y < 300; y++ {
		for x := 0; x < 400; x++ {
			src.SetRGBA(x, y, color.RGBA{R: 200, G: 100, B: 50, A: 255})
		}
	}
	out := downscale(src, 100)
	if out.Bounds().Dx() != 100 || out.Bounds().Dy() != 75 {
		t.Fatalf("尺寸不对: %v", out.Bounds())
	}
	r, g, b, a := out.At(50, 40).RGBA()
	if r>>8 != 200 || g>>8 != 100 || b>>8 != 50 || a>>8 != 255 {
		t.Fatalf("颜色失真: %d,%d,%d,%d", r>>8, g>>8, b>>8, a>>8)
	}
}

// 不放大：maxW 大于原宽时原样返回
func TestDownscaleNoUpscale(t *testing.T) {
	src := image.NewRGBA(image.Rect(0, 0, 640, 360))
	out := downscale(src, 1280)
	if out.Bounds() != src.Bounds() {
		t.Fatalf("不该放大: %v", out.Bounds())
	}
}

// 非 RGBA 源（通用 At 路径）同样可用
func TestDownscaleGenericSource(t *testing.T) {
	type rawImg struct{ *image.RGBA } // 包装后不再是 *image.RGBA 的具体类型断言
	var src image.Image = rawImg{image.NewRGBA(image.Rect(0, 0, 200, 100))}
	out := downscale(src, 50)
	if out.Bounds().Dx() != 50 || out.Bounds().Dy() != 25 {
		t.Fatalf("通用路径尺寸不对: %v", out.Bounds())
	}
}
