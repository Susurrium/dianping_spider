# -*- coding:utf-8 -*-
"""
达美乐评论自动浏览工具
脚本在搜索框自动输入店铺名，用户点击选店后自动滚动评论
"""
import json, os, time, subprocess, sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, 'mitm_logs')
PROGRESS_FILE = os.path.join(LOG_DIR, 'browse_progress.json')

def load_stores():
    import openpyxl
    wb = openpyxl.load_workbook(os.path.join(BASE_DIR, '达美乐_门店爬虫.xlsx'))
    ws = wb.active
    stores = []
    for row in ws.iter_rows(min_row=3, values_only=True):
        name = row[1] if len(row) > 1 and row[1] else None
        if name:
            stores.append(str(name).strip())
    return stores

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {'completed': [], 'index': 0}

def save_progress(p):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(p, f, ensure_ascii=False, indent=2)

def count_reviews():
    return len([f for f in os.listdir(LOG_DIR) if f.startswith('review_') and f.endswith('.json')])

def get_wechat_wid():
    r = subprocess.run(['xdotool', 'search', '--name', '微信'], capture_output=True, text=True)
    for wid in r.stdout.strip().split('\n'):
        if wid:
            return int(wid)
    return None

def focus(wid):
    subprocess.run(['xdotool', 'windowactivate', str(wid)], capture_output=True)
    subprocess.run(['xdotool', 'windowfocus', str(wid)], capture_output=True)
    time.sleep(0.3)

def type_text(text):
    subprocess.run(['xdotool', 'type', '--clearmodifiers', '--delay', '30', text], capture_output=True)
    time.sleep(0.3)

def key(k):
    subprocess.run(['xdotool', 'key', k], capture_output=True)
    time.sleep(0.2)

def scroll(wid, n=5):
    for _ in range(n):
        subprocess.run(['xdotool', 'click', '5'], capture_output=True)
        time.sleep(0.15)
    time.sleep(0.5)

def main():
    print("=" * 60)
    print("🍕 达美乐评论自动浏览工具")
    print("=" * 60)
    
    stores = load_stores()
    progress = load_progress()
    completed = set(progress.get('completed', []))
    idx = progress.get('index', 0)
    
    print(f"📋 共 {len(stores)} 家店铺, 已完成 {len(completed)} 家")
    
    wid = get_wechat_wid()
    if not wid:
        print("❌ 未找到微信窗口")
        return
    print(f"✅ 微信窗口: {wid}")
    
    print("\n💡 请确保已打开达美乐小程序并进入搜索页面")
    input("   准备好后按 Enter 开始...\n")
    
    for i in range(idx, len(stores)):
        name = stores[i]
        if name in completed:
            continue
        
        print(f"\n[{i+1}/{len(stores)}] 📍 {name}")
        
        # 聚焦微信
        focus(wid)
        time.sleep(0.3)
        
        # 清除搜索框并输入新店铺名
        # 先全选清除
        key('ctrl+a')
        time.sleep(0.1)
        
        # 输入店铺名
        type_text(name)
        time.sleep(0.3)
        
        # 按Enter搜索
        key('Return')
        
        # 等待用户点击店铺
        old_count = count_reviews()
        print(f"   ⏳ 请在搜索结果中点击「{name}」...")
        
        # 等待检测到新评论文件（说明用户已点击进入店铺）
        waited = 0
        while waited < 120:
            if count_reviews() > old_count:
                break
            time.sleep(2)
            waited += 2
            if waited % 10 == 0:
                print(f"   ⏳ 已等待{waited}秒...")
        
        if waited >= 120:
            print(f"   ⚠️ 超时，跳过")
            continue
        
        print(f"   ✅ 检测到店铺已打开，开始自动滚动评论...")
        time.sleep(1)
        
        # 自动滚动评论
        no_new = 0
        for page in range(100):
            prev = count_reviews()
            scroll(wid, 8)
            time.sleep(2)
            
            if count_reviews() == prev:
                no_new += 1
                if no_new >= 3:
                    print(f"   📄 滚动{page+1}页后无更多评论")
                    break
            else:
                no_new = 0
                if page % 5 == 0:
                    print(f"   📄 滚动第{page+1}页...")
        
        # 记录完成
        completed.add(name)
        progress['completed'] = list(completed)
        progress['index'] = i + 1
        save_progress(progress)
        print(f"   ✅ 完成!")
        
        # 提示用户返回搜索
        print(f"\n   💡 请按返回键回到搜索页面，然后按 Enter 继续下一家...")
        input()
    
    print(f"\n🎉 全部完成！共处理 {len(completed)} 家店铺")

if __name__ == '__main__':
    main()
