"""应用级共享状态访问器（2026-09-18 新增）。

背景（真实故障）：analyzers/ 里原来用 `from main import jobs` 懒加载主进程的 jobs。
但主程序是用 `python main.py` 启动的，它的模块名是 `__main__`；`from main import ...`
会让 Python 把 main.py **再执行一遍**（这次模块名是 `main`）。第二遍执行到 main.py
第 37 行 `_fc.jobs = jobs` 时，会把 chat/function_call.py 的模块级 `jobs` 重新指向
"第二个 main" 自己的 jobs 快照——从此与真正在服务的那个 jobs 脱钩，而且那份快照
再也不会收到新上传的任务。

后果：任何走 chat/function_call.py 的功能（AI 对话 / 深度分析）对新上传的任务
一律报「日志目录不存在，请重新上传」；analyze_summary 也匹配不到新任务的缓存报告。

用法：子模块需要访问运行中主进程的状态时，一律用这里，不要再 `import main`。
"""
import sys

_RUNNING_NAMES = ("__main__", "main")


def get_app_module():
    """返回正在运行的主程序模块（带 jobs 属性的那个）；取不到返回 None。"""
    for name in _RUNNING_NAMES:
        m = sys.modules.get(name)
        if m is not None and hasattr(m, "jobs"):
            return m
    return None


def get_jobs() -> dict:
    """运行中主进程的 jobs 字典；取不到时返回空 dict（不抛异常）。"""
    m = get_app_module()
    return getattr(m, "jobs", {}) if m is not None else {}


def get_main_attr(name, default=None):
    """取运行中主程序模块上的属性（如 ANALYZERS / _STANDARD_TYPES）。"""
    m = get_app_module()
    return getattr(m, name, default) if m is not None else default
