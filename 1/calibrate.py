#!/usr/bin/env python3
"""
测试不同 tick 数（25/30/35/40/45/50）下的耗时和成功率
找到临界值：刚好能触发加载，又不浪费动画时间
"""
import json, subprocess, time, sys, signal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from human_click import get_window, load_points, parse_coord
from review_exporter import load_stores_from_xlsx

XLSX = ROOT / '门店抽样.xlsx'
if not XLSX.exists():
    XLSX = ROOT / '达美乐_门店.xlsx'
OUT_DIR = ROOT / 'output' / 'store_reviews'
TARGET = Path('/tmp/mitm_target.json')


def review_count(idx, name):
    f = OUT_DIR / f"{idx:03d}_{name.replace('/','_')}.json"
    if not f.exists():
        return 0
    try:
        return len(json.loads(f.read_text(encoding='utf-8')))
    except:
        return 0


def scroll_burst(wid, n_ticks, delay_ms=8):
    args = ['xdotool']
    for i in range(n_ticks):
        args += ['click', '--window', str(wid), '5']
        if i < n_ticks - 1:
            args += ['sleep', f'{delay_ms/1000:.4f}']
    subprocess.run(args, check=False, capture_output=True)


def wait_api(idx, name, last, max_wait=2.5):
    start = time.time()
    while time.time() - start < max_wait:
        cur = review_count(idx, name)
        if cur > last:
            return cur, True
        time.sleep(0.015)
    return review_count(idx, name), False


def main():
    if len(sys.argv) < 2:
        print("用法: python3 calibrate.py <编号>")
        return 1
    
    idx = int(sys.argv[1])
    stores = load_stores_from_xlsx(XLSX)
    name = stores[idx-1].name
    print(f"测试店: {idx:03d} {name}")
    
    if not subprocess.run(['pgrep', '-f', 'mitmdump'], capture_output=True).stdout.strip():
        print("❌ mitmdump 没在跑")
        return 1
    
    TARGET.write_text(json.dumps({'idx': idx, 'name': name}, ensure_ascii=False))
    win = get_window()
    if not win:
        print("❌ 没微信窗口")
        return 1
    
    points = load_points()
    rx, ry = parse_coord(points['review_list_anchor'])
    subprocess.run(['xdotool', 'windowactivate', '--sync', str(win['wid'])], check=False)
    time.sleep(0.3)
    subprocess.run(['xdotool', 'mousemove', str(win['x']+rx), str(win['y']+ry)], check=False)
    time.sleep(0.3)
    
    print("确认在评价页 Enter...")
    input()
    
    # 测各种 tick 数
    results = {}
    for n_ticks in [20, 25, 30, 35, 40, 45]:
        print(f"\n=== {n_ticks} ticks ===")
        success_count = 0
        total_time = 0
        scroll_times = []
        
        for trial in range(4):
            last = review_count(idx, name)
            
            t0 = time.time()
            scroll_burst(win['wid'], n_ticks)
            scroll_dur = time.time() - t0
            
            t1 = time.time()
            cur, got = wait_api(idx, name, last, max_wait=4.0)
            wait_dur = time.time() - t1
            
            total = scroll_dur + wait_dur
            total_time += total
            scroll_times.append(scroll_dur)
            
            mark = '✅' if got else '❌'
            print(f"  T{trial+1}: 滚{scroll_dur*1000:.0f}ms 等{wait_dur*1000:.0f}ms +{cur-last} {mark}")
            
            if got:
                success_count += 1
            time.sleep(1.0)  # 小冷却
        
        avg_scroll = sum(scroll_times) / len(scroll_times)
        results[n_ticks] = {
            'success': success_count,
            'avg_scroll_ms': avg_scroll * 1000,
            'avg_total': total_time / 4,
        }
        print(f"  → {success_count}/4 成功, 滚动平均 {avg_scroll*1000:.0f}ms")
    
    print("\n=== 总结 ===")
    print(f"{'ticks':<8}{'成功率':<12}{'滚动耗时':<14}{'每轮总耗时':<14}{'估算速度':<14}")
    for n, r in results.items():
        rate = r['success'] / 4
        if rate > 0:
            est_per_min = (rate * 14) / r['avg_total'] * 60
        else:
            est_per_min = 0
        print(f"{n:<8}{rate*100:.0f}%{' ':<8}{r['avg_scroll_ms']:.0f}ms{' ':<8}{r['avg_total']:.1f}s{' ':<10}{est_per_min:.0f}条/分")
    
    print("\n💡 找到 100% 成功率且耗时最短的 tick 数，就是最优值")


if __name__ == '__main__':
    sys.exit(main() or 0)
