// clouddiag-bridge — 云端AI远程运维助手 · 透明管道化桥接器
//
// 设计原则（v2 管道化）：
//  1. 单一职责：只做「命令管道 + 文件通道」，把服务器的命令送进本地 shell，
//     把结果送回来。不内置任何业务工具。
//  2. 平台无关：同一份代码交叉编译出 Windows / Linux / macOS 版本。
//  3. 透明可审计：本地日志记录每一条执行过的命令；控制台显示连接状态；
//     不静默后台、不请求管理员权限、不自启动。
//  4. 行为面最小：能靠执行命令实现的能力，一律不内置。
package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"net"
	"os"
	"os/signal"
	"runtime"
	"strings"
	"syscall"
)

// Version 桥接器版本号（构建时可用 -ldflags 覆盖）
var Version = "1.0.2"

// ClientInfo 上报给服务器的本机身份信息
type ClientInfo struct {
	Hostname string `json:"hostname"`
	OS       string `json:"os"`
	Platform string `json:"platform"` // windows | linux | darwin
	Arch     string `json:"arch"`
	LocalIP  string `json:"local_ip"`
	Username string `json:"username"`
	Version  string `json:"version"`
	Bridge   string `json:"bridge"`   // "go-pipe"
	IsAdmin  bool   `json:"is_admin"` // 当前是否以管理员权限运行
}

// normalizeServerURL 容错处理用户输入的服务器地址：
//
//	http://host:port  → ws://host:port
//	https://host:port → wss://host:port
//	host:port（无协议）→ ws://host:port
//	ws:// / wss:// 原样保留
func normalizeServerURL(s string) string {
	s = strings.TrimSpace(s)
	s = strings.TrimRight(s, "/")
	switch {
	case strings.HasPrefix(s, "http://"):
		return "ws://" + strings.TrimPrefix(s, "http://")
	case strings.HasPrefix(s, "https://"):
		return "wss://" + strings.TrimPrefix(s, "https://")
	case strings.HasPrefix(s, "ws://"), strings.HasPrefix(s, "wss://"):
		return s
	default:
		return "ws://" + s
	}
}

func main() {
	var serverURL, roomCode, token string
	var elevate, elevated, noElevate bool
	var interactiveFlag bool
	flag.StringVar(&serverURL, "server", "ws://localhost:8000", "服务器地址 (ws:// 或 wss://)")
	flag.StringVar(&roomCode, "room", "", "房间码（必填）")
	flag.StringVar(&token, "token", "", "连接令牌（一键连接下发）")
	flag.BoolVar(&elevate, "elevate", false, "自动请求管理员权限（Windows UAC 提权）")
	flag.BoolVar(&noElevate, "no-elevate", false, "禁止自动提权（特殊情况用，默认双击自动提权）")
	flag.BoolVar(&elevated, "elevated", false, "内部标志：已处于提权后的进程")
	flag.BoolVar(&interactiveFlag, "interactive", false, "交互式输入房间码（默认行为：打印用法后退出，不阻塞终端）")
	flag.Parse()
	// 统一规范化服务器地址（交互输入与命令行参数都容错 http:// / 漏协议）
	serverURL = normalizeServerURL(serverURL)

	// 默认服务器地址（2026-09-21 配置化：不再硬编码具体部署地址）：
	//   优先级：命令行 -server > 环境变量 CLOUDDIAG_SERVER > 内置占位默认
	//   部署方应通过一键连接命令（带 -server 参数）或环境变量指定自己的服务器
	const defaultServer = "ws://localhost:8000"
	if serverURL == "" || serverURL == "ws://localhost:8000" {
		if env := os.Getenv("CLOUDDIAG_SERVER"); env != "" {
			serverURL = normalizeServerURL(env)
		} else {
			serverURL = defaultServer
		}
	}

	// 交互模式：双击运行 / 未提供房间码时，引导用户输入
	// 而不是直接报错退出（避免"闪退"）
	// 交互模式（2026-09-21 修复「同名冲突阻塞」事故）：
	//   历史问题：无参数运行时会阻塞等待房间码输入。
	//   而 Linux 上本程序曾名为 bridge，与系统网络工具 bridge-utils 同名，
	//   客户误执行 bridge 时被本程序「劫持」终端并卡住（事故记录见 docs/风险与事故记录/）。
	//
	//   现在的行为：
	//     · 非交互式环境（无 TTY，如脚本/管道调用）→ 打印用法后退出，绝不阻塞
	//     · 有 TTY 且未加 --interactive → 打印用法后退出（不打扰）
	//     · 显式加 --interactive → 进入交互式输入房间码（双击场景）
	if roomCode == "" {
		useTTY := isTerminal(os.Stdin)
		if !interactiveFlag && !useTTY {
			printUsage(serverURL)
			os.Exit(2)
		}
		if !interactiveFlag && useTTY {
			// 有终端但未显式要求交互：提示用法后退出，避免误运行卡住终端
			printUsage(serverURL)
			fmt.Println(" 提示：如需交互输入房间码，请加 --interactive 参数；")
			fmt.Println("       或用一键连接命令（自动带上房间码与令牌）。")
			os.Exit(0)
		}
		reader := bufio.NewReader(os.Stdin)
		fmt.Println("==============================================")
		fmt.Println(" 云端AI远程运维助手 · 桥接器 v" + Version)
		fmt.Println("----------------------------------------------")
		fmt.Printf(" 服务器: %s\n", serverURL)
		fmt.Println("----------------------------------------------")
		fmt.Print(" 房间码 (8位, 例如 ABC12345): ")
		room, _ := reader.ReadString('\n')
		room = strings.TrimSpace(strings.ToUpper(room))
		if room == "" {
			fmt.Fprintln(os.Stderr, "错误: 房间码不能为空")
			fmt.Println("按回车键退出...")
			_, _ = reader.ReadString('\n')
			os.Exit(2)
		}
		roomCode = room
		fmt.Println("----------------------------------------------")
		fmt.Printf(" 即将连接服务器 %s · 房间 %s\n", serverURL, roomCode)
		fmt.Println("==============================================")
		fmt.Println("")
	}

	// 管理员提权（仅 Windows 有意义）：
	//   方案 A：双击（交互模式）→ 自动请求管理员权限，不再询问；
	//   命令行显式 --elevate 也提权；--no-elevate 可禁止（特殊情况）。
	//   提权后新进程带 --elevated 标志自动跳过，防递归。
	//   用户拒绝 UAC（点"否"）→ 提权失败 → 继续以普通权限运行。
	if !isAdmin() && !elevated && !noElevate {
		shouldElevate := elevate || flag.NFlag() == 0
		if shouldElevate {
			fmt.Println(" 正在请求管理员权限（UAC 弹窗确认后自动继续）…")
			if err := elevateSelf(serverURL, roomCode, token); err != nil {
				fmt.Fprintf(os.Stderr, " 提权失败（可能拒绝了 UAC）: %v\n", err)
				fmt.Println(" 继续以普通权限运行（部分功能受限，如 BIOS 全量读取）。")
			} else {
				// 提权成功：新进程已启动，本进程退出
				fmt.Println(" 已触发提权，请在新的管理员窗口中查看连接状态。")
				os.Exit(0)
			}
		} else {
			fmt.Println(" 当前为普通权限运行（部分功能受限，如 BIOS 全量读取）。如需提权请加 --elevate 参数。")
		}
	}

	serverURL = strings.TrimRight(serverURL, "/")

	// 令牌：命令行参数优先，其次环境变量 BRIDGE_TOKEN
	if token == "" {
		token = os.Getenv("BRIDGE_TOKEN")
	}

	logger := NewAuditLogger()
	info := collectClientInfo()
	logger.Info("bridge %s 启动 (pid=%d, os=%s/%s, host=%s)",
		Version, os.Getpid(), info.Platform, info.Arch, info.Hostname)

	// 注册退出信号，优雅断开
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt, syscall.SIGTERM)

	cfg := &Config{
		ServerURL: serverURL,
		RoomCode:  roomCode,
		Token:     token,
		Info:      info,
		Logger:    logger,
	}

	c := NewClient(cfg)

	go func() {
		<-sig
		logger.Info("收到退出信号，正在断开…")
		c.Shutdown()
		os.Exit(0)
	}()

	// 阻塞运行（内部自动重连）
	c.Run()
}

// isTerminal 判断是否连接了交互式终端（TTY）
// 2026-09-21：用于避免在非交互环境下阻塞等待输入（同名冲突事故的修复配套）
func isTerminal(f *os.File) bool {
	fi, err := f.Stat()
	if err != nil {
		return false
	}
	return (fi.Mode() & os.ModeCharDevice) != 0
}

// printUsage 打印用法说明（无参数运行时的安全出口——不阻塞）
func printUsage(serverURL string) {
	fmt.Println("==============================================")
	fmt.Println(" 云端AI远程运维助手 · 桥接器 v" + Version)
	fmt.Println("----------------------------------------------")
	fmt.Printf(" 服务器: %s\n", serverURL)
	fmt.Println("----------------------------------------------")
	fmt.Println(" 用法：")
	fmt.Println("   clouddiag-bridge -server <地址> -room <房间码> [-token <令牌>]")
	fmt.Println("")
	fmt.Println(" 常用参数：")
	fmt.Println("   -server    服务器地址（ws:// 或 wss://，或 http/https 自动转换）")
	fmt.Println("   -room      房间码（8 位，一键连接命令会自动带上）")
	fmt.Println("   -token     连接令牌（由云端一键连接命令下发）")
	fmt.Println("   -interactive  交互式输入房间码（默认不进入，避免阻塞终端）")
	fmt.Println("   -elevate   请求管理员权限（Windows UAC）")
	fmt.Println("   -no-elevate  禁止自动提权")
	fmt.Println("")
	fmt.Println(" 环境变量：CLOUDDIAG_SERVER 可指定默认服务器地址")
	fmt.Println("==============================================")
}

// collectClientInfo 采集本机身份信息（纯只读，无副作用）
func collectClientInfo() ClientInfo {
	hostname, _ := os.Hostname()
	username := os.Getenv("USER")
	if username == "" {
		username = os.Getenv("USERNAME")
	}
	if username == "" {
		username = "unknown"
	}
	return ClientInfo{
		Hostname: hostname,
		OS:       runtime.GOOS,
		Platform: runtime.GOOS,
		Arch:     runtime.GOARCH,
		LocalIP:  localIP(),
		Username: username,
		Version:  Version,
		Bridge:   "go-pipe",
		IsAdmin:  isAdmin(),
	}
}

// localIP 取本机第一块非回环 IPv4 地址（尽力而为）
func localIP() string {
	ifaces, err := net.Interfaces()
	if err != nil {
		return ""
	}
	for _, iface := range ifaces {
		if iface.Flags&net.FlagLoopback != 0 || iface.Flags&net.FlagUp == 0 {
			continue
		}
		addrs, err := iface.Addrs()
		if err != nil {
			continue
		}
		for _, a := range addrs {
			ip := strings.Split(a.String(), "/")[0]
			if strings.Contains(ip, ":") {
				continue
			}
			return ip
		}
	}
	return ""
}

// MarshalJSON 调试用：打印消息时不输出敏感内容
func debugJSON(v interface{}) string {
	b, err := json.Marshal(v)
	if err != nil {
		return fmt.Sprintf("<json err: %v>", err)
	}
	if len(b) > 400 {
		return string(b[:400]) + "…(truncated)"
	}
	return string(b)
}
