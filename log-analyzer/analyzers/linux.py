"""Linux diagnostic analyzers."""
from pathlib import Path
from datetime import datetime
from collections import Counter
import json
import re
from app_state import get_jobs  # 2026-09-18：不要 import main（会二次导入 main.py）

# REPORT_DIR is defined in detectors.py — reference it via main's import
# We compute it here for standalone use (e.g., testing)
from pathlib import Path as _Path
REPORT_DIR = _Path(__file__).resolve().parent.parent / "reports"


def _find_sos_root(log_dir: Path) -> Path:
    """
    For Linux sosreports, find_log_dir returns .../var/log/.
    Walk up to find the sosreport root directory so we can access
    /etc/os-release, /proc/cpuinfo, etc.
    """
    # If we're inside var/log, go up 2 levels to sosreport root
    if log_dir.name == "log" and log_dir.parent.name == "var":
        return log_dir.parent.parent
    # If we're inside a deeper var/log, find the sosreport root
    for p in [log_dir] + list(log_dir.parents):
        if (p / "etc").is_dir() or (p / "proc").is_dir():
            return p
        if p.name.startswith("sosreport-") or p.name.startswith("sos_"):
            return p
    return log_dir


def _extract_varlog_info(log_dir: Path) -> dict:
    """从 /var/log 常规日志兜底提取硬件/系统信息(纯 var/log 包、无 sosreport 结构时启用)。

    来源:
      - kern.log / dmesg:内核版本、OS 版本线索、DMI 主板、BIOS 版本、内存、CPU、NVIDIA 平台
      - dpkg.log:linux-image 包版本(OS 补丁级)、nvidia-driver 包版本
      - Xorg.0.log:NVIDIA 显卡型号、驱动版本
    """
    info = {"os_info": {}, "cpu": "", "cpu_cores": 0, "memory": {},
            "bios": "", "board": "", "gpu": "", "nvidia_driver": "",
            "disks": [], "nics": [], "usb": [], "software": {},
            "secureboot": "", "arch": "", "timezone": ""}

    def find_log(*names):
        # 按 names 优先级查找(而非 rglob 遍历顺序),dmesg 优先于 kern.log
        for n in names:
            for f in log_dir.rglob("*"):
                if f.is_file() and f.name.lower() == n:
                    return f
        return None

    def read_lines(fp, limit=60000):
        try:
            return fp.read_text(encoding="utf-8", errors="replace").split("\n")[:limit]
        except Exception:
            return []

    # ── dmesg(优先,指南推荐)/ kern.log 兜底 ──
    kern = find_log("dmesg", "dmesg.0", "dmesg.log", "kern.log", "kern.log.1")
    disk_map = {}  # dev → 容量(按设备名去重)
    usb_seen = set()
    # kern.log 也参与 USB 扫描(热插拔设备只在 kern.log,不在 dmesg)
    usb_src = find_log("kern.log", "kern.log.1", "syslog")
    if kern:
        klines = read_lines(kern)
        # CPU 核数:smpboot Total(最准);dmesg 无则 kern.log 兜底
        bogo_m = re.search(r"smpboot: Total of (\d+) processors.*?\(([\d.]+) BogoMIPS\)", "\n".join(klines[:2000]))
        if not bogo_m:
            k2 = find_log("kern.log", "kern.log.1")
            if k2:
                bogo_m = re.search(r"smpboot: Total of (\d+) processors.*?\(([\d.]+) BogoMIPS\)", "\n".join(read_lines(k2)[:2000]))
        if bogo_m:
            info["cpu_cores"] = int(bogo_m.group(1))
            info["bogo"] = bogo_m.group(2)
        else:
            info["cpu_cores"] = len([l for l in klines if "smpboot: CPU" in l])
        # 主机名:日志行第 3 字段(Jan 4 14:20:39 SikunStation kernel:),从 kern.log/syslog 提取
        hn_src = usb_src or kern
        for line in read_lines(hn_src)[:300]:
            m = re.match(r"^\w{3}\s+\d+\s+[\d:]+ (\S+)", line)
            if m and not info["os_info"].get("hostname"):
                info["os_info"]["hostname"] = m.group(1)
                break
        for line in klines:
            # 内核版本 + OS 版本线索
            m = re.search(r"Linux version ([\w.+-]+) .*\(Ubuntu ([^)]+)\)", line)
            if m:
                if not info["os_info"].get("kernel"):
                    info["os_info"]["kernel"] = m.group(1)
                if not info["os_info"].get("os_release"):
                    info["os_info"]["os_release"] = m.group(2)
            # DMI 主板型号
            m = re.search(r"DMI: ([\w ]+)/([\w]+)", line)
            if m and not info["board"]:
                info["board"] = m.group(1) if m.group(2) == "INVALID" else f"{m.group(1)} ({m.group(2)})"
            # BIOS 版本 + 日期
            m = re.search(r"BIOS ([\w.]+) (\d{2}/\d{2}/\d{4})", line)
            if m and not info["bios"]:
                info["bios"] = f"{m.group(1)} ({m.group(2)})"
            # 内存总量
            m = re.search(r"Memory: \d+K/(\d+)K available", line)
            if m and not info["memory"].get("MemTotal"):
                info["memory"]["MemTotal"] = f"{int(m.group(1)) // 1024} MB"
            # 内存插槽占用
            m = re.search(r"Memory slots populated: (\d+)/(\d+)", line)
            if m and not info["memory"].get("slots"):
                info["memory"]["slots"] = f"{m.group(1)}/{m.group(2)}"
            # CPU 型号(model name 或 smpboot CPU0)
            m = re.search(r"model name\s*:\s*(.+)", line)
            if m and not info["cpu"]:
                info["cpu"] = m.group(1).strip()
            m = re.search(r"smpboot: CPU0: ([\w ():,.-]+)", line)
            if m and not info["cpu"]:
                info["cpu"] = m.group(1).strip()
            # NVIDIA 平台线索(ACPI 表)
            if "NVIDIA" in line and not info["gpu"] and ("NVSDEV" in line or "NBCI" in line):
                info["gpu"] = "NVIDIA 平台(ACPI 表存在)"
            # 显卡(PCI VGA/3D/Display controller)
            m = re.search(r"(?:VGA compatible controller|3D controller|Display controller):\s*(.+)", line)
            if m and not info["gpu"]:
                info["gpu"] = m.group(1).strip()
            # 显卡 vendor ID(10de=NVIDIA / 1002=AMD / 8086=Intel)
            m = re.search(r"\[(10de|1002|8086):[\da-f]{4}\]", line)
            if m and not info["gpu"] and ("VGA" in line or "3D" in line or "Display" in line):
                vendor = {"10de": "NVIDIA", "1002": "AMD", "8086": "Intel"}[m.group(1)]
                info["gpu"] = f"{vendor} 显卡 (PCI ID {m.group(0).strip('[]')})"
            # 显卡(PCI class 0x030000=VGA / 0x030200=3D 格式):pci 0000:e1:00.0: [10de:1ff2] type 00 class 0x030000
            m = re.search(r"\[(10de|1002|8086):([\da-f]{4})\] type \d+ class 0x0(?:30000|30200)", line)
            if m and not info["gpu"]:
                vendor = {"10de": "NVIDIA", "1002": "AMD", "8086": "Intel"}[m.group(1)]
                dev = m.group(2)
                model = {"1ff2": "RTX A4000", "2230": "RTX A6000", "2206": "RTX A5000",
                         "2504": "RTX A2000", "2684": "RTX 4090", "2687": "RTX 3090",
                         "2203": "RTX A6000", "26b9": "RTX A4000 Ada", "2531": "RTX A4500 Ada"}.get(dev, "")
                info["gpu"] = f"{vendor} 显卡{(' ' + model) if model else ''} (PCI ID {m.group(1)}:{dev})"
            # NVRM 驱动版本(NVIDIA)
            m = re.search(r"NVRM: loading NVIDIA .*?Kernel Module ([\d.]+)", line)
            if m and not info["nvidia_driver"]:
                info["nvidia_driver"] = f"NVRM {m.group(1)}"
            # CPU 频率
            m = re.search(r"tsc: Detected ([\d.]+) MHz processor", line)
            if m and not info.get("cpu_freq"):
                info["cpu_freq"] = f"{m.group(1)} MHz"
            # 网卡(PCI Ethernet controller)
            m = re.search(r"Ethernet controller:\s*(.+)", line)
            if m and m.group(1).strip() not in info["nics"]:
                info["nics"].append(m.group(1).strip())
            # 网卡名(eth0/eno1/enpXsY)去重
            m = re.search(r"\b(eth\d+|eno\d+|enp\S+):", line)
            if m and m.group(1) not in info["nics"]:
                info["nics"].append(m.group(1))
            # 硬盘(块设备 sda/sdb/nvme0n1 + 容量,按设备名去重,保留首次非 0 值)
            m = re.search(r"\[(s[a-z]+|nvme\d+n\d+)\]\s+\d+ 512-byte logical blocks: \(([\d.]+ \w+)/([\d.]+ \w+)\)", line)
            if m:
                dev, cap = m.group(1), m.group(3)
                if dev not in disk_map or disk_map[dev] == "0 B":
                    disk_map[dev] = cap
            # 磁盘接口类型(SATA link up 优先 / NVMe 兜底)
            m = re.search(r"ata\d+: SATA link up ([\d.]+ Gbps)", line)
            if m:
                info["disk_interface"] = f"SATA ({m.group(1)})"
            elif not info.get("disk_interface") and "nvme" in line.lower():
                info["disk_interface"] = "NVMe"
            # USB 设备(New USB device found + Product,去重限 8 个;dmesg + kern.log 合并)
            usb_lines = klines if usb_src is None or usb_src == kern else klines + read_lines(usb_src)
            for ul in usb_lines:
                if "New USB device found" in ul:
                    m2 = re.search(r"usb [\w-]+: New USB device found, idVendor=([\da-f]{4}), idProduct=([\da-f]{4})", ul)
                    if m2:
                        usb_seen.add(f"{m2.group(1)}:{m2.group(2)}")
                if "Product:" in ul and "usb" in ul.lower():
                    m2 = re.search(r"Product:\s*(.+)", ul)
                    if m2 and len(info["usb"]) < 8:
                        prod = m2.group(1).strip()
                        if prod not in info["usb"]:
                            info["usb"].append(prod)
            # 安全启动 / 架构
            m = re.search(r"secureboot: Secure boot (\w+)", line)
            if m and not info["secureboot"]:
                info["secureboot"] = m.group(1).lower()
            m = re.search(r"Detected architecture (\S+)", line)
            if m and not info["arch"]:
                info["arch"] = m.group(1).rstrip(".")

    # ── dpkg.log:OS 补丁级 / NVIDIA 驱动包 ──
    dpkg = find_log("dpkg.log")
    if dpkg:
        for line in read_lines(dpkg):
            m = re.search(r"install (linux-image-[\w.+-]+):", line)
            if m and not info["os_info"].get("kernel_pkg"):
                info["os_info"]["kernel_pkg"] = m.group(1)
            m = re.search(r"install (nvidia-driver-[\d.]+[^:]*|nvidia-kernel-open-[\d.]+):", line)
            if m and not info["nvidia_driver"]:
                info["nvidia_driver"] = m.group(1)

    # ── Xorg.0.log:NVIDIA 显卡型号 / 驱动 ──
    xorg = find_log("Xorg.0.log", "xorg.log")
    if xorg:
        for line in read_lines(xorg, 800):
            m = re.search(r"NVIDIA\(0\):\s*(NVIDIA [\w ]+?) \(", line)
            if m and (not info["gpu"] or info["gpu"].startswith("NVIDIA 平台")):
                info["gpu"] = m.group(1).strip()
            m = re.search(r"NVIDIA: (?:driver|module) version ([\d.]+)", line)
            if m and not info["nvidia_driver"]:
                info["nvidia_driver"] = m.group(1)

    info["disks"] = [f"{d} ({c})" for d, c in disk_map.items()]

    # ── syslog:软件/服务(桌面环境、Docker)──
    syslog = find_log("syslog", "syslog.1", "messages")
    if syslog:
        for line in read_lines(syslog, 20000):
            if "gdm" in line.lower() and "gdm-x-session" in line and not info["software"].get("desktop"):
                info["software"]["desktop"] = "GNOME (GDM3 显示管理器)"
            m = re.search(r"Docker daemon .*?version=([\d.]+)", line)
            if m and not info["software"].get("docker"):
                info["software"]["docker"] = f"Docker {m.group(1)}"
            if not info["timezone"]:
                m = re.search(r"[\dT+\-]*([+-]\d{2}:\d{2})", line)
                if m and m.group(1) in ("+08:00", "+09:00", "-05:00", "+00:00"):
                    info["timezone"] = f"UTC{m.group(1)}"

    # ── auth.log:主要用户 ──
    auth = find_log("auth.log", "auth.log.1")
    if auth:
        for line in read_lines(auth, 10000):
            m = re.search(r"session opened for user (\w+)\(uid=(\d+)\)", line)
            if m and m.group(2) in ("1000", "1001", "1002"):
                info["software"]["user"] = f"{m.group(1)} (uid {m.group(2)})"
                break
            m = re.search(r"session opened for user (\w+)", line)
            if m and m.group(1) not in ("root", "lightdm", "gdm"):
                info["software"]["user"] = m.group(1)
                break

    return info


def analyze_linux_overview(log_dir: Path) -> dict:
    """📄 Linux 系统概览：提取 OS/内核/硬件信息"""
    root = _find_sos_root(log_dir)

    def read_first(path: str, max_kb: int = 50) -> str:
        fp = root / path
        if not fp.exists():
            for alt in root.rglob(path):
                fp = alt
                break
        if not fp.exists():
            return ""
        size = fp.stat().st_size
        with open(fp, 'r', encoding='utf-8', errors='replace') as f:
            return f.read(min(size, max_kb * 1024))

    def find_read(pattern: str, max_kb: int = 50) -> str:
        # rglob with wildcard pattern like *os-release*
        for fname in root.rglob(pattern):
            if fname.is_file():
                return read_first(str(fname.relative_to(root)), max_kb)
        return ""

    # OS info
    os_info = {}
    release = find_read('*os-release*') or find_read('*lsb-release*')
    if release:
        for line in release.split('\n'):
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                os_info[k.lower()] = v.strip("'\"")

    # Kernel version — try proc/version, then dmesg
    kernel_ver = find_read('proc/version*', 5) or find_read('dmesg*', 10)
    if kernel_ver:
        m = re.search(r'Linux version ([\S]+)', kernel_ver)
        if m:
            os_info['kernel'] = m.group(1)
        elif not os_info.get('kernel'):
            # Fallback: extract from uname -r output
            uname_r = find_read('*uname*', 2)
            if uname_r:
                os_info['kernel'] = uname_r.strip().split('\n')[0].strip()

    # Hostname
    hostname = find_read('*hostname*', 2)
    if hostname:
        os_info['hostname'] = hostname.strip()

    # Uptime
    uptime = find_read('proc/uptime*', 1)
    if uptime:
        parts = uptime.strip().split()
        if parts:
            try:
                secs = float(parts[0])
                days = int(secs // 86400)
                hours = int((secs % 86400) // 3600)
                os_info['uptime'] = f"{days}天{hours}小时" if days > 0 else f"{int(secs/3600)}小时"
            except:
                os_info['uptime'] = uptime.strip()

    # CPU info
    cpu_info = find_read('proc/cpuinfo*', 20) or find_read('*cpuinfo*', 20)
    cpu_model = ""
    cpu_cores = 0
    if cpu_info:
        for line in cpu_info.split('\n'):
            if 'model name' in line.lower() and ':' in line:
                cpu_model = line.split(':', 1)[1].strip()
                break
        cpu_cores = len([l for l in cpu_info.split('\n') if l.startswith('processor')])

    # Memory info
    mem = {}
    mem_info = find_read('proc/meminfo*', 10) or find_read('*meminfo*', 10)
    if mem_info:
        for key in ['MemTotal', 'MemAvailable', 'SwapTotal', 'MemFree']:
            m = re.search(rf'{key}:\s+(\d+)', mem_info)
            if m:
                kb = int(m.group(1))
                mem[key] = f"{kb // 1024} MB" if kb >= 1024 else f"{kb} kB"

    # Disk info from /proc/mounts or /etc/fstab
    disks = []
    nics = []
    mounts_info = find_read('proc/mounts*', 20) or find_read('*fstab*', 10)
    if mounts_info:
        for line in mounts_info.split('\n'):
            if line.startswith('/dev/') or line.startswith('UUID='):
                disks.append(line.strip()[:120])

    # Files in the log directory for reference
    file_list = {}
    for f in sorted(log_dir.rglob('*')):
        if f.is_file():
            rel = str(f.relative_to(log_dir))
            size_kb = round(f.stat().st_size / 1024, 1)
            file_list[rel] = {"size": f.stat().st_size, "kb": size_kb}

    # ── /var/log 兜底提取(纯 var/log 包无 sosreport 结构时)──
    vlog_used = False
    if not os_info:
        vlog = _extract_varlog_info(log_dir)
        if vlog["os_info"]:
            os_info = vlog["os_info"]
            vlog_used = True
        cpu_model = cpu_model or vlog["cpu"]
        cpu_cores = cpu_cores or vlog["cpu_cores"]
        mem = {**mem, **vlog["memory"]} if vlog["memory"] else mem
        os_info["board"] = vlog["board"]
        os_info["bios"] = vlog["bios"]
        os_info["gpu"] = vlog["gpu"]
        os_info["nvidia_driver"] = vlog["nvidia_driver"]
        disks = disks or vlog["disks"]
        nics = vlog["nics"]
        os_info["secureboot"] = vlog["secureboot"]
        os_info["arch"] = vlog["arch"]
        os_info["timezone"] = vlog["timezone"]
        os_info["usb"] = vlog["usb"]
        os_info["disk_interface"] = vlog.get("disk_interface", "")
        os_info["software"] = vlog["software"]
        if vlog.get("cpu_freq"):
            os_info["cpu_freq"] = vlog["cpu_freq"]
        if vlog.get("bogo"):
            os_info["bogo"] = vlog["bogo"]
        # OS 名称解析:6.5.0-18.18~22.04.1 → "Ubuntu 22.04"
        if not os_info.get("name") and os_info.get("os_release"):
            m = re.search(r"~(2\d\.\d+)", os_info["os_release"])
            if m:
                os_info["name"] = f"Ubuntu {m.group(1)}"
        # LTS 代号:22.04 → LTS (Jammy)
        if not os_info.get("lts") and os_info.get("os_release"):
            m = re.search(r"~(2\d\.\d+)", os_info["os_release"])
            if m:
                code = {"20.04": "Focal", "22.04": "Jammy", "24.04": "Noble"}.get(m.group(1))
                if code:
                    os_info["lts"] = f"LTS ({code})"
        if vlog["board"] or vlog["bios"] or vlog["gpu"] or vlog["nvidia_driver"] or vlog["disks"] or vlog["nics"]:
            vlog_used = True

    return {
        "title": "📄 Linux 系统概览",
        "os_info": os_info,
        "cpu": cpu_model,
        "cpu_cores": cpu_cores,
        "memory": mem,
        "disks": disks,
        "nics": nics,
        "files": file_list,
        "file_count": len(file_list),
        "varlog_fallback": vlog_used,
        "summary": (
            f"{os_info.get('pretty_name', os_info.get('name', os_info.get('os_release', 'Linux')))} | "
            f"内核 {os_info.get('kernel', '?')} | "
            f"{os_info.get('board', '') or '?'} | "
            f"BIOS {os_info.get('bios', '?')} | "
            f"{cpu_model or '?'} | "
            f"{mem.get('MemTotal', '?')}"
        ),
    }


def analyze_linux_kernel(log_dir: Path) -> dict:
    """🔧 Linux 内核诊断：OOM killer / kernel panic / 硬件错误"""
    MAX_MB = 3

    def read_logs(names: list, max_mb: int = MAX_MB) -> str:
        """Read all files matching any of the given name patterns — top-level only."""
        texts = []
        total = 0
        for f in sorted(log_dir.iterdir()):
            if f.is_file() and any(n.lower() in f.name.lower() for n in names):
                size = f.stat().st_size
                with open(f, 'r', encoding='utf-8', errors='replace') as fh:
                    texts.append(fh.read(min(size, max_mb * 1024 * 1024)))
                total += min(size, max_mb * 1024 * 1024)
                if total > 10 * 1024 * 1024:  # max 10MB total
                    break
        # If nothing found at top level, try subdirectories (for non-standard layouts)
        if not texts:
            for f in sorted(log_dir.rglob('*')):
                if f.is_file() and not str(f.relative_to(log_dir)).startswith('.') \
                        and any(n.lower() in f.name.lower() for n in names):
                    size = f.stat().st_size
                    with open(f, 'r', encoding='utf-8', errors='replace') as fh:
                        texts.append(fh.read(min(size, max_mb * 1024 * 1024)))
                    total += min(size, max_mb * 1024 * 1024)
                    if total > 10 * 1024 * 1024:
                        break
        return '\n'.join(texts)

    # Search kern, dmesg, AND messages (kernel messages often merged there)
    kern_text = read_logs(['kern', 'dmesg', 'messages'])

    findings = []
    severity = "ok"

    # OOM killer — broader pattern
    oom_pattern = re.compile(
        r'(?:Out of memory|invoked oom-killer|oom_reaper|OOM kill)',
        re.IGNORECASE
    )
    oom_events = oom_pattern.findall(kern_text)
    if oom_events:
        findings.append(f"🔴 OOM Killer 被触发 {len(oom_events)} 次")
        severity = "critical"

    # Kernel panic / oops / BUG — broader patterns
    panic_pattern = re.compile(
        r'(?:Kernel panic|'
        r'general protection fault|'
        r'Unable to handle kernel|'
        r'NMI watchdog:|'
        r'rcu_sched detected stalls|'
        r'INFO: task .* blocked for more than|'
        r'BUG: (?:unable to handle|soft lockup|Bad page|'
        r'scheduling while atomic|spinlock|sleeping function|'
        r'DMA-API|memory leak|list_(?:add|del) corruption|'
        r'NULL pointer|kernel NULL pointer|'
        r'stack guard page|'
        r'workqueue lockup))',
        re.IGNORECASE
    )
    panics = panic_pattern.findall(kern_text)
    if panics:
        findings.append(f"🔴 内核严重错误 {len(panics)} 次")
        if severity == "ok":
            severity = "critical"

    # Hardware errors (MCE, PCIe, disk)
    hw_pattern = re.compile(
        r'(?:Hardware Error|machine check exception|'
        r'PCIe.*error|'
        r'ata\d+\.\d+.*(?:error|exception|failed|timeout)|'
        r'sector.*error|I/O error|'
        r'link down|'
        r'EDAC.*error|mcelog|'
        r'SMART.*error|'
        r'blk_update_request.*I/O error|'
        r'Buffer I/O error|'
        r' EXT4-fs error)',
        re.IGNORECASE
    )
    hw_errs = hw_pattern.findall(kern_text)
    if hw_errs:
        findings.append(f"🔧 硬件/磁盘错误 {len(hw_errs)} 条")
        if severity == "ok":
            severity = "warning"

    # Segmentation faults
    segfaults = re.findall(r'segfault at', kern_text, re.IGNORECASE)
    if segfaults:
        findings.append(f"⚠️ 段错误 (segfault) {len(segfaults)} 次")

    # Temperature / thermal warnings
    thermal = re.findall(
        r'(?:thermal.*throttl|overheat|critical temperature|'
        r'thermal zone|Cooling Dev)',
        kern_text, re.IGNORECASE
    )
    if thermal:
        findings.append(f"🌡️ 温度/散热告警 {len(thermal)} 条")
        if severity == "ok":
            severity = "warning"

    # Extract key timeline events with timestamps
    timeline = []
    ts_pat = re.compile(
        r'((?:\w{3}\s+\d+\s+)?\d{2}:\d{2}:\d{2}).*?'
        r'(?:panic|oops|OOM|error|fail|BUG|killed)',
        re.IGNORECASE
    )
    for m in ts_pat.finditer(kern_text):
        entry = m.group(0)[:200]
        if entry not in timeline:
            timeline.append(entry)
        if len(timeline) >= 50:
            break

    if not findings:
        findings.append("✅ 内核日志未发现异常")

    return {
        "title": "🔧 Linux 内核诊断",
        "severity": severity,
        "findings": findings,
        "oom_count": len(oom_events),
        "panic_count": len(panics),
        "hw_error_count": len(hw_errs),
        "segfault_count": len(segfaults),
        "thermal_count": len(thermal),
        "timeline": timeline[:30],
        "summary": (
            f"{len(oom_events)}次OOM / {len(panics)}次严重错误 / "
            f"{len(hw_errs)}条硬件异常"
        ),
    }


def analyze_linux_syslog(log_dir: Path) -> dict:
    """📋 Linux 系统日志：服务崩溃/认证失败/磁盘错误"""
    MAX_MB = 3

    def read_logs(names: list, max_mb: int = MAX_MB) -> str:
        texts = []
        total = 0
        for f in sorted(log_dir.iterdir()):
            if f.is_file() and any(n.lower() in f.name.lower() for n in names):
                size = f.stat().st_size
                with open(f, 'r', encoding='utf-8', errors='replace') as fh:
                    texts.append(fh.read(min(size, max_mb * 1024 * 1024)))
                total += min(size, max_mb * 1024 * 1024)
                if total > 8 * 1024 * 1024:
                    break
        if not texts:
            for f in sorted(log_dir.rglob('*')):
                if f.is_file() and not str(f.relative_to(log_dir)).startswith('.') \
                        and any(n.lower() in f.name.lower() for n in names):
                    size = f.stat().st_size
                    with open(f, 'r', encoding='utf-8', errors='replace') as fh:
                        texts.append(fh.read(min(size, max_mb * 1024 * 1024)))
                    total += min(size, max_mb * 1024 * 1024)
                    if total > 8 * 1024 * 1024:
                        break
        return '\n'.join(texts)

    # Search syslog, messages, kern, daemon, secure, boot
    syslog_text = read_logs([
        'syslog', 'messages', 'kern', 'daemon', 'secure', 'boot', 'auth'
    ])

    findings = []
    severity = "ok"
    stats = {}

    # Service failures — broader patterns including systemd exit codes
    svc_fails = re.findall(
        r'(?:service.*?failed|process.*?died|'
        r'exited with|killed by signal|'
        r'Failed with result|start operation timed out|'
        r'Failed to start|dependency failed)',
        syslog_text, re.IGNORECASE
    )
    stats['service_failures'] = len(svc_fails)

    # Authentication failures
    auth_fails = re.findall(
        r'(?:authentication failure|Failed password|invalid user|'
        r'pam_unix.*auth|authentication error|'
        r'Connection closed by authenticating|'
        r'Unable to authenticate)',
        syslog_text, re.IGNORECASE
    )
    stats['auth_failures'] = len(auth_fails)

    # Disk/storage errors
    disk_errs = re.findall(
        r'(?:I/O error|read error|write error|'
        r'filesystem.*error|ext4.*error|btrfs.*error|xfs.*error|'
        r'Buffer I/O error|'
        r'smartd.*FAIL|'
        r'UNC error|media error)',
        syslog_text, re.IGNORECASE
    )
    stats['disk_errors'] = len(disk_errs)

    # Network errors
    net_errs = re.findall(
        r'(?:network.*unreachable|connection.*refused|'
        r'timeout|dhcp.*fail|link.*down|'
        r'Name or service not known|'
        r'Cannot resolve|'
        r'nslcd.*connection)',
        syslog_text, re.IGNORECASE
    )
    stats['network_errors'] = len(net_errs)

    # Build findings with meaningful thresholds
    if stats['service_failures'] >= 100:
        findings.append(f"🔴 服务失败 {stats['service_failures']} 次（频繁）")
        severity = "critical"
    elif stats['service_failures'] > 0:
        findings.append(f"🟡 服务失败 {stats['service_failures']} 次")
        severity = "warning"

    if stats['auth_failures'] > 10:
        findings.append(f"🔴 认证失败 {stats['auth_failures']} 次（可能有暴力破解尝试）")
        if severity != "critical":
            severity = "warning"
    elif stats['auth_failures'] > 0:
        findings.append(f"📝 认证失败 {stats['auth_failures']} 次")

    if stats['disk_errors'] > 0:
        findings.append(f"🔴 磁盘/文件系统错误 {stats['disk_errors']} 条")
        severity = "critical"

    if stats['network_errors'] > 50:
        findings.append(f"🟡 网络错误 {stats['network_errors']} 条（较频繁）")
        if severity == "ok":
            severity = "warning"
    elif stats['network_errors'] > 0:
        findings.append(f"📡 网络错误 {stats['network_errors']} 条")

    if not findings:
        findings.append("✅ 系统日志未发现明显异常")

    return {
        "title": "📋 Linux 系统日志",
        "severity": severity,
        "findings": findings,
        "stats": stats,
        "summary": (
            f"服务失败{stats['service_failures']}次 / "
            f"认证失败{stats['auth_failures']}次 / "
            f"磁盘错误{stats['disk_errors']}条"
        ),
    }


def analyze_linux_summary(log_dir: Path) -> dict:
    """📊 Linux 综合总结：聚合各子报告"""
    results = {}
    findings = []
    severity = "ok"

    sev_map = {"critical": 3, "warning": 2, "ok": 1}
    max_sev = 1
    max_sev_name = "ok"

    # Find which job this tslog belongs to by scanning reports directory
    current_job = None
    for report_file in sorted(REPORT_DIR.glob("*_linux_overview.json"), reverse=True):
        try:
            with open(report_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Try to match by checking if the log directory exists
            job_id = report_file.stem.replace("_linux_overview", "")
        except:
            continue

    # Try to find job by matching tslog_path in-memory
    # 2026-09-18 修复：不再 `from main import jobs`（会把 main.py 二次导入，
    # 使 chat 用的 jobs 变成旧快照 → 新任务 AI 对话报「日志目录不存在」）
    _jobs = get_jobs()
    for job_key in list(_jobs.keys()):
        if _jobs[job_key].get('tslog_path') == str(log_dir):
            current_job = job_key
            break

    # If we can't find the job, try to infer from report files
    if not current_job:
        # Strategy 1: scan all report files and match by path similarity
        for rp in sorted(REPORT_DIR.glob("*_linux_overview.json"), reverse=True):
            try:
                with open(rp, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # Check if any file path in the overview matches our tslog
                files = data.get('files', {})
                # Check if relative paths match
                candidate_job = rp.stem.replace("_linux_overview", "")
                # Simple heuristic: if report modified within 24h of log_dir
                if rp.stat().st_mtime - log_dir.stat().st_mtime < 86400:
                    current_job = candidate_job
                    break
            except:
                continue
    
    # Strategy 2: Just use the most recently created overview report
    if not current_job:
        newest = None
        newest_time = 0
        for rp in REPORT_DIR.glob("*_linux_overview.json"):
            try:
                mtime = rp.stat().st_mtime
                if mtime > newest_time:
                    newest_time = mtime
                    newest = rp.stem.replace("_linux_overview", "")
            except:
                pass
        if newest and (datetime.now().timestamp() - newest_time) < 86400:
            current_job = newest

    if current_job:
        for atype in ["linux_overview", "linux_kernel", "linux_syslog"]:
            rp = REPORT_DIR / f"{current_job}_{atype}.json"
            if rp.exists():
                try:
                    with open(rp, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        results[atype] = data
                        for finding in data.get('findings', [])[:3]:
                            if finding not in findings and "未发现异常" not in finding:
                                findings.append(finding)
                        s = data.get('severity', 'ok')
                        if sev_map.get(s, 1) > max_sev:
                            max_sev = sev_map[s]
                            max_sev_name = s
                except Exception:
                    pass

    if not findings:
        findings.append("📝 请先运行「内核诊断」和「系统日志」分析以生成综合报告")

    return {
        "title": "📊 Linux 综合总结",
        "severity": max_sev_name,
        "findings": findings[:15],
        "detail": {
            k: {
                "title": v.get("title", k),
                "summary": v.get("summary", ""),
            }
            for k, v in results.items()
        },
    }
