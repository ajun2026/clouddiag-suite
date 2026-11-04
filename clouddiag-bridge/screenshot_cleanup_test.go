package main

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

// 2026-11-04：观察帧此前从不清理（前缀不匹配）。这里锁住口径：
// preview 只留最新 3 帧，shot 超过 24 小时才删。
func TestCleanupShots(t *testing.T) {
	dir := t.TempDir()
	mk := func(name string, age time.Duration) string {
		p := filepath.Join(dir, name)
		if err := os.WriteFile(p, []byte("x"), 0o644); err != nil {
			t.Fatal(err)
		}
		m := time.Now().Add(-age)
		if err := os.Chtimes(p, m, m); err != nil {
			t.Fatal(err)
		}
		return p
	}
	var previews []string
	for i := 0; i < 6; i++ {
		previews = append(previews, mk("nexpert-preview-ROOM-20261104-00000"+string(rune('0'+i))+".jpg", time.Duration(10-i)*time.Minute))
	}
	oldShot := mk("nexpert-shot-ROOM-20261101-100000.png", 30*time.Hour)
	newShot := mk("nexpert-shot-ROOM-20261104-170000.png", 2*time.Hour)

	cleanupShots(dir)

	ents, _ := os.ReadDir(dir)
	var leftPreview, leftShot int
	for _, e := range ents {
		switch {
		case len(e.Name()) > 16 && e.Name()[:16] == "nexpert-preview-":
			leftPreview++
		case len(e.Name()) > 13 && e.Name()[:13] == "nexpert-shot-":
			leftShot++
		}
	}
	if leftPreview != 3 {
		t.Fatalf("观察帧应保留 3 个，实际 %d", leftPreview)
	}
	if _, err := os.Stat(oldShot); !os.IsNotExist(err) {
		t.Fatalf("30 小时前的高清截图应被删除")
	}
	if _, err := os.Stat(newShot); err != nil {
		t.Fatalf("2 小时前的高清截图应保留: %v", err)
	}
}
