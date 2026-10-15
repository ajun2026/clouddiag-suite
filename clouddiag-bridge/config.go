package main

// Config 桥接器运行配置
type Config struct {
	ServerURL  string     // ws:// 或 wss:// 服务器地址
	RoomCode   string     // 房间码
	Token      string     // 连接令牌（一键连接下发，服务器校验）
	MaxRetries int        // 连续连接失败上限（达到即停止重连；<=0 表示不限制）
	Info       ClientInfo // 上报的本机身份
	Logger     *AuditLogger
}
