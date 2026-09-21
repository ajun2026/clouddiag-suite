//go:build !windows

package main

import "fmt"

// isAdmin 非 Windows 平台：Linux/macOS 的 bridge 通常以普通用户运行，
// 提权机制不同（sudo），这里不自动提权，统一返回 false。
// 服务器端可据此提示用户自行用 sudo 运行。
func isAdmin() bool {
	return false
}

// elevateSelf 非 Windows 平台不支持自动提权
func elevateSelf(serverURL, roomCode, token string) error {
	return fmt.Errorf("当前平台不支持自动提权，请手动以管理员/root 权限运行")
}
