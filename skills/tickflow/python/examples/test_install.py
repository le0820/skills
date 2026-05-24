#!/usr/bin/env python3
"""
测试脚本：验证 TickFlow、web_search、QVeris、MinerU 服务可用性
用法：python examples/test_install.py
"""

import os
import sys
import subprocess
import json

# 添加 skills 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ──────────────────────────────────────────────
# 颜色输出
# ──────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

results = {}

def ok(msg):
    print(f"  {GREEN}✅{RESET} {msg}")
    return True

def fail(msg):
    print(f"  {RED}❌{RESET} {msg}")
    return False

def skip(msg):
    print(f"  {YELLOW}⏭️{RESET}  {msg}")
    return None

def header(title):
    print(f"\n{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}\n")

# ──────────────────────────────────────────────
# 1. TickFlow 免费服务
# ──────────────────────────────────────────────
def test_tickflow_free():
    header("1. TickFlow 免费服务（历史行情）")
    try:
        from tickflow import TickFlow
        tf = TickFlow.free()
        df = tf.klines.get("600000.SH", period="1d", count=3, as_dataframe=True)
        if df is not None and len(df) > 0:
            print(f"  获取到 {len(df)} 条 K 线数据：")
            print(df.tail(3).to_string())
            return ok("TickFlow 免费服务可用")
        else:
            return fail("返回数据为空")
    except Exception as e:
        return fail(f"免费服务异常: {e}")

# ──────────────────────────────────────────────
# 2. TickFlow 完整服务（API Key）
# ──────────────────────────────────────────────
def test_tickflow_full():
    header("2. TickFlow 完整服务（API Key）")
    api_key = os.environ.get("TICKFLOW_API_KEY", "")
    if not api_key:
        return fail("未设置 TICKFLOW_API_KEY 环境变量")

    print(f"  API Key: {api_key[:20]}...{api_key[-8:] if len(api_key) > 28 else ''}")
    
    try:
        from tickflow import TickFlow
        tf = TickFlow(api_key=api_key)
        instruments = tf.instruments.batch(symbols=["600000.SH", "AAPL.US"])
        count = 0
        for inst in instruments:
            print(f"  {inst['symbol']}: {inst.get('name', 'N/A')}")
            count += 1
        if count >= 1:
            return ok(f"TickFlow 完整服务可用（查询到 {count} 只标的）")
        else:
            return fail("返回结果为空")
    except Exception as e:
        return fail(f"完整服务异常: {e}")

# ──────────────────────────────────────────────
# 3. web_search 可用性
# ──────────────────────────────────────────────
def test_web_search():
    header("3. web_search 可用性")
    print("  注意：web_search 由 OpenClaw 网关调用，此脚本仅检查配置完整性。\n")
    
    # 检查 openclaw.json 中的 web search 配置
    config_path = os.path.expanduser("~/.openclaw/openclaw.json")
    try:
        with open(config_path) as f:
            config = json.load(f)
        
        web_search = config.get("tools", {}).get("web", {}).get("search", {})
        enabled = web_search.get("enabled", False)
        provider = web_search.get("provider", "unknown")
        
        print(f"  配置状态: {'enabled' if enabled else 'disabled'}")
        print(f"  搜索提供商: {provider}")
        
        # 检查 moonshot plugin
        moonshot = config.get("plugins", {}).get("entries", {}).get("moonshot", {})
        moonshot_enabled = moonshot.get("enabled", False)
        has_api_key = bool(moonshot.get("config", {}).get("webSearch", {}).get("apiKey"))
        
        print(f"  Moonshot 插件: {'enabled' if moonshot_enabled else 'disabled'}")
        print(f"  API Key: {'已配置' if has_api_key else '未配置'}")
        
        if enabled and moonshot_enabled and has_api_key:
            return ok("web_search 配置完整（提供商: {0}）".format(provider))
        elif not enabled:
            return fail("web_search 未启用")
        else:
            return fail(f"web_search 配置不完整 (enabled={enabled}, plugin={moonshot_enabled}, key={has_api_key})")
    except FileNotFoundError:
        return fail("找不到 openclaw.json 配置文件")
    except Exception as e:
        return fail(f"配置检查异常: {e}")

# ──────────────────────────────────────────────
# 4. QVeris Plugin 可用性
# ──────────────────────────────────────────────
def test_qveris():
    header("4. QVeris Plugin 可用性")
    
    # 检查 openclaw.json 中的 QVeris 配置
    config_path = os.path.expanduser("~/.openclaw/openclaw.json")
    try:
        with open(config_path) as f:
            config = json.load(f)
        
        plugins_allow = config.get("plugins", {}).get("allow", [])
        qveris_entry = config.get("plugins", {}).get("entries", {}).get("qveris", {})
        
        qveris_enabled = qveris_entry.get("enabled", False)
        has_api_key = bool(qveris_entry.get("config", {}).get("apiKey"))
        in_allowlist = "qveris" in plugins_allow
        
        print(f"  在 allow 列表: {'是' if in_allowlist else '否'}")
        print(f"  插件启用: {'是' if qveris_enabled else '否'}")
        print(f"  API Key: {'已配置' if has_api_key else '未配置'}")
        
        # 检查扩展目录
        load_path = config.get("plugins", {}).get("load", {}).get("paths", [])
        qveris_path = [p for p in load_path if "qveris" in p]
        print(f"  扩展路径: {qveris_path[0] if qveris_path else '未找到'}")
        
        # 检查扩展文件是否存在
        if qveris_path:
            ext_dir = qveris_path[0]
            if os.path.isdir(ext_dir):
                files = os.listdir(ext_dir)
                print(f"  扩展文件数: {len(files)}")
            else:
                print(f"  {RED}扩展目录不存在{RESET}")
                return fail(f"QVeris 扩展目录不存在: {ext_dir}")
        
        if in_allowlist and qveris_enabled and has_api_key and qveris_path:
            return ok("QVeris Plugin 配置完整")
        else:
            issues = []
            if not in_allowlist: issues.append("未在 allow 列表")
            if not qveris_enabled: issues.append("未启用")
            if not has_api_key: issues.append("缺少 API Key")
            if not qveris_path: issues.append("缺少扩展路径")
            return fail(f"QVeris 配置不完整: {', '.join(issues)}")
    except FileNotFoundError:
        return fail("找不到 openclaw.json 配置文件")
    except Exception as e:
        return fail(f"QVeris 检查异常: {e}")

# ──────────────────────────────────────────────
# 5. MinerU 服务可用性
# ──────────────────────────────────────────────
def test_mineru():
    header("5. MinerU 服务可用性")
    
    token = os.environ.get("MINERU_TOKEN", "")
    if not token:
        return fail("未设置 MINERU_TOKEN 环境变量")
    
    print(f"  Token 前缀: {token[:30]}...")
    
    # 检查 mineru-open-api 是否安装
    try:
        result = subprocess.run(
            ["mineru-open-api", "version"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            print(f"  CLI 版本: {result.stdout.strip()}")
        else:
            return fail(f"mineru-open-api 返回错误: {result.stderr}")
    except FileNotFoundError:
        # 尝试 npm prefix 路径
        local_bin = os.path.expanduser("~/.local/bin/mineru-open-api")
        if os.path.exists(local_bin):
            print(f"  CLI 路径: {local_bin}")
        else:
            return fail("mineru-open-api 未安装")
    
    # 验证 token
    try:
        auth_cmd = ["mineru-open-api", "auth", "--verify"]
        # 也尝试从 ~/.local/bin 查找
        local_bin = os.path.expanduser("~/.local/bin/mineru-open-api")
        if os.path.exists(local_bin):
            auth_cmd[0] = local_bin
        
        env = os.environ.copy()
        env["MINERU_TOKEN"] = token
        
        result = subprocess.run(
            auth_cmd, capture_output=True, text=True, timeout=30, env=env
        )
        if result.returncode == 0:
            print(f"  Token 验证: {result.stdout.strip()}")
            return ok("MinerU 服务可用（Token 有效）")
        else:
            print(f"  stdout: {result.stdout.strip()}")
            print(f"  stderr: {result.stderr.strip()}")
            return fail(f"MinerU Token 验证失败 (exit={result.returncode})")
    except subprocess.TimeoutExpired:
        return fail("MinerU Token 验证超时")
    except Exception as e:
        return fail(f"MinerU 检查异常: {e}")

# ──────────────────────────────────────────────
# 汇总
# ──────────────────────────────────────────────
def summary():
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  测试结果汇总{RESET}")
    print(f"{BOLD}{'='*60}{RESET}\n")
    
    passed = sum(1 for v in results.values() if v is True)
    failed = sum(1 for v in results.values() if v is False)
    skipped = sum(1 for v in results.values() if v is None)
    total = len(results)
    
    for name, status in results.items():
        if status is True:
            icon = f"{GREEN}✅{RESET}"
        elif status is False:
            icon = f"{RED}❌{RESET}"
        else:
            icon = f"{YELLOW}⏭️{RESET}"
        print(f"  {icon}  {name}")
    
    print(f"\n  {GREEN}通过: {passed}{RESET}  {RED}失败: {failed}{RESET}  {YELLOW}跳过: {skipped}{RESET}  总计: {total}")
    
    if failed > 0:
        print(f"\n  {RED}{BOLD}存在失败项，请检查上述错误信息。{RESET}")
        sys.exit(1)
    else:
        print(f"\n  {GREEN}{BOLD}所有测试通过！{RESET}")
        sys.exit(0)

# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
if __name__ == "__main__":
    print(f"{BOLD}{CYAN}")
    print("╔══════════════════════════════════════════════════╗")
    print("║          OpenClaw 服务可用性测试脚本            ║")
    print("╚══════════════════════════════════════════════════╝")
    print(RESET)
    
    print(f"  TICKFLOW_API_KEY = {'已设置' if os.environ.get('TICKFLOW_API_KEY') else '未设置'}")
    print(f"  MINERU_TOKEN      = {'已设置' if os.environ.get('MINERU_TOKEN') else '未设置'}")
    
    # 按顺序执行测试
    tests = [
        ("TickFlow 免费服务", test_tickflow_free),
        ("TickFlow 完整服务", test_tickflow_full),
        ("web_search", test_web_search),
        ("QVeris Plugin", test_qveris),
        ("MinerU 服务", test_mineru),
    ]
    
    for name, func in tests:
        results[name] = func()
    
    summary()
