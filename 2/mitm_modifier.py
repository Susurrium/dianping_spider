# -*- coding:utf-8 -*-
"""
mitmproxy请求修改器
拦截评论API请求，修改referid指向目标店铺
同时记录签名头用于分析
"""
import json
import os
from mitmproxy import http

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mitm_logs')
QUEUE_FILE = os.path.join(LOG_DIR, 'shop_queue.json')
RESULT_FILE = os.path.join(LOG_DIR, 'collected_reviews.json')

# 当前目标店铺
current_target = None
collected = {}

def request(flow: http.HTTPFlow) -> None:
    """在请求发出前修改"""
    global current_target
    
    url = flow.request.url
    if 'outsidesiftedreviewlist' not in url and 'outsideshopreviewlist' not in url:
        return
    
    # 记录原始请求的签名头
    mtgsig = flow.request.headers.get('mtgsig', '')
    if mtgsig:
        # 保存签名样本用于分析
        sig_file = os.path.join(LOG_DIR, 'mtgsig_samples.json')
        samples = []
        if os.path.exists(sig_file):
            with open(sig_file) as f:
                samples = json.load(f)
        samples.append({
            'mtgsig': mtgsig,
            'url': url[:300],
            'params': dict(flow.request.query),
        })
        # 只保留最近20个样本
        with open(sig_file, 'w') as f:
            json.dump(samples[-20:], f, ensure_ascii=False, indent=2)
    
    # 如果有目标店铺队列，修改referid
    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE) as f:
                queue = json.load(f)
            if queue:
                target = queue[0]
                original_referid = flow.request.query.get('referid', '')
                
                # 修改referid
                flow.request.query['referid'] = target['uuid']
                # 重置start为0（从头开始获取）
                flow.request.query['start'] = '0'
                
                current_target = target
                print(f"\n🔀 重定向: {original_referid} → {target['uuid']} ({target['name']})")
        except:
            pass


def response(flow: http.HTTPFlow) -> None:
    """处理响应"""
    global current_target
    
    url = flow.request.url
    if 'outsidesiftedreviewlist' not in url and 'outsideshopreviewlist' not in url:
        return
    
    if not current_target:
        return
    
    try:
        data = json.loads(flow.response.text)
        review_list = data.get('data', {}).get('list', [])
        
        if review_list:
            shop_name = current_target['name']
            uuid = current_target['uuid']
            
            if uuid not in collected:
                collected[uuid] = {
                    'name': shop_name,
                    'uuid': uuid,
                    'reviews': [],
                }
            
            for r in review_list:
                if isinstance(r, dict):
                    fu = r.get('feedUser', {})
                    collected[uuid]['reviews'].append({
                        'userName': fu.get('userName', '') if isinstance(fu, dict) else '',
                        'text': r.get('text', '') or r.get('content', ''),
                        'time': r.get('time', ''),
                        'star': r.get('star', ''),
                    })
            
            print(f"  📝 {shop_name}: +{len(review_list)}条 (共{len(collected[uuid]['reviews'])}条)")
            
            # 如果返回不足一页，说明这家店抓完了
            if len(review_list) < 15:
                # 移到下一家
                _next_shop()
        
        # 保存结果
        with open(RESULT_FILE, 'w', encoding='utf-8') as f:
            json.dump(collected, f, ensure_ascii=False, indent=2)
    
    except Exception as e:
        print(f"  ❌ 错误: {e}")


def _next_shop():
    """移到下一家店铺"""
    try:
        with open(QUEUE_FILE) as f:
            queue = json.load(f)
        if queue:
            finished = queue.pop(0)
            print(f"  ✅ 完成: {finished['name']}")
            with open(QUEUE_FILE, 'w') as f:
                json.dump(queue, f, ensure_ascii=False, indent=2)
            if queue:
                print(f"  ⏭️ 下一家: {queue[0]['name']}")
            else:
                print(f"  🎉 全部完成！")
    except:
        pass


print("=" * 60)
print("🔀 请求修改器已启动")
print(f"📁 {LOG_DIR}")
print("等待店铺队列...")
print("=" * 60)
