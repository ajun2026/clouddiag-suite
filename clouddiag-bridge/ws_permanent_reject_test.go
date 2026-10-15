package main

import (
	"testing"
)

// TestDispatchErrorPermanentReject 覆盖"永久拒绝 vs 临时故障"的判定分支：
//   - 服务端 error 帧带 fatal=true（机器可读，优先）
//   - 老服务端不带 fatal → 关键词兜底（含"已结束诊断/归档/已闲置/令牌"等）
//   - 两者都不满足 → 视为临时故障（继续重连，不应误判为永久）
func TestDispatchErrorPermanentReject(t *testing.T) {
	c := &Client{cfg: &Config{Logger: NewAuditLogger(), RoomCode: "TESTROOM", MaxRetries: 10}}

	cases := []struct {
		name string
		msg  map[string]interface{}
		want bool
	}{
		{"fatal=true 且无关键词 → 永久", map[string]interface{}{"type": "error", "fatal": true, "content": "服务器拒绝了一个没有关键词的原因"}, true},
		{"fatal=true 且无内容 → 永久", map[string]interface{}{"type": "error", "fatal": true}, true},
		{"无 fatal，含「已结束诊断」→ 永久（2026-10-15 新增关键词）", map[string]interface{}{"type": "error", "content": "房间已结束诊断，连接将断开。"}, true},
		{"无 fatal，含「归档」→ 永久", map[string]interface{}{"type": "error", "content": "房间已结束诊断（归档）。历史记录仍可查看。"}, true},
		{"无 fatal，含「房间已闲置」→ 永久", map[string]interface{}{"type": "error", "content": "房间已闲置。请回到对话页重新获取一键连接。"}, true},
		{"无 fatal，英文 not found → 永久", map[string]interface{}{"type": "error", "content": "Room not found."}, true},
		{"无 fatal，含「HTTP 401」→ 永久（握手拒绝）", map[string]interface{}{"type": "error", "content": "HTTP 401 Unauthorized: websocket: bad handshake"}, true},
		{"fatal=false 且无关键词 → 临时（应继续重连）", map[string]interface{}{"type": "error", "fatal": false, "content": "服务器内部错误，请稍后重试"}, false},
		{"无 fatal 无关键词（普通错误）→ 临时", map[string]interface{}{"type": "error", "content": "分析脚本下载失败（客户机网络异常）"}, false},
	}

	for _, tc := range cases {
		err := c.dispatch(tc.msg)
		got := isPermanentReject(err)
		if got != tc.want {
			t.Errorf("%s: isPermanentReject=%v，期望 %v（err=%v）", tc.name, got, tc.want, err)
			continue
		}
		t.Logf("✅ %s → 永久=%v", tc.name, got)
	}
}

// TestKeywordListCoversArchived 防止回归：归档/结束诊断类文案必须被判定为永久拒绝。
func TestKeywordListCoversArchived(t *testing.T) {
	for _, s := range []string{
		"房间已结束诊断，连接将断开。如需继续诊断，请回到对话页重新获取一键连接。",
		"房间已结束诊断（归档）。历史记录仍可查看，如需继续诊断，请回到对话页重新获取一键连接。",
		"房间已关闭。",
		"会话已结束。",
	} {
		if !isPermanentReject(&permanentRejectError{Reason: s}) {
			t.Errorf("文案未被判定为永久拒绝: %s", s)
		}
	}
}
