# -*- coding:utf-8 -*-
"""
SSL Key Logger 收集器：用 tshark + SSLKEYLOGFILE 解密 PC 微信小程序流量，
喂给 dianping_interceptor 现有解析逻辑。

使用方式：

1. 启动 PC 微信带 SSLKEYLOGFILE：
   SSLKEYLOGFILE=/tmp/wx_keys.log /home/.../WeChatLinux_x86_64.AppImage &

2. 离线解析 pcap（验证 / 补抓）：
   python3 sslkey_collector.py --pcap /tmp/wx_capture/raw.pcap

3. 实时模式（生产）：
   python3 sslkey_collector.py --live --iface wlp2s0
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# 复用 dianping_interceptor 的现有解析逻辑
from dianping_events import append_event, build_event
import dianping_interceptor as dpi


LOG_DIR = ROOT / 'mitm_logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)
EVENTS_FILE = LOG_DIR / 'events.jsonl'

DIANPING_HOSTS = [
    'mapi.dianping.com',
    'm.dianping.com',
    'catfront.dianping.com',
]

# 我们关心的 API path 关键字（用于过滤）
API_KEYWORDS = (
    'outsidesiftedreviewlist',
    'outsideshopreviewlist',
    'shopreview',
    'wxsearch/search',
    'searchshop',
    'minitakeoutsearch.bin',
    'unifyshopaggregatedump.bin',
    'wxupdatecities.bin',
    'hotsuggest.bin',
    'recommendpoi',
    'searchindexprompt.bin',
    'homeresource.bin',
    'chosenrankentry.bin',
)

# 只关心 dianping 流量（避免 catfront 的 metric 噪音淹没）
INTERESTING_HOSTS_FOR_EVENTS = ('mapi.dianping.com', 'm.dianping.com')


# ----------------------------------------------------------------------
# tshark 包装
# ----------------------------------------------------------------------

def _check_tshark():
    if not shutil.which('tshark'):
        sys.stderr.write("❌ 未找到 tshark，请先 apt install tshark\n")
        sys.exit(1)


def _run_tshark(args: List[str], input_data: Optional[bytes] = None,
                check: bool = True, timeout: int = 60) -> str:
    cmd = ['tshark'] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, input=input_data, check=check)
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"⚠️ tshark 失败: {' '.join(cmd[:3])}... rc={e.returncode}\n")
        return e.stdout or ''
    except subprocess.TimeoutExpired:
        sys.stderr.write(f"⚠️ tshark 超时: {' '.join(cmd[:3])}...\n")
        return ''
    return r.stdout


# ----------------------------------------------------------------------
# 从 pcap 中提取 HTTP/HTTP2 请求-响应对（含 metadata 和 body）
# ----------------------------------------------------------------------

def extract_http_pairs(pcap_path: Path, keys_path: Path) -> List[Dict[str, Any]]:
    """
    从 pcap 提取所有 HTTP/HTTP2 请求-响应对。
    返回列表，每项 dict: {url, method, status, host, path, query, request_headers,
                          request_body, response_headers, response_body, timestamp}
    """
    if not pcap_path.exists() or pcap_path.stat().st_size < 100:
        return []

    # 第一步：用 --export-objects 把所有响应 body dump 出来（按 path 命名）
    # 文件名 = 响应里的 path（含 query string）
    dump_dir = Path('/tmp/wx_dump') / pcap_path.stem
    if dump_dir.exists():
        shutil.rmtree(dump_dir, ignore_errors=True)
    dump_dir.mkdir(parents=True, exist_ok=True)

    _run_tshark([
        '-r', str(pcap_path),
        '-o', f'tls.keylog_file:{keys_path}',
        '--export-objects', f'http,{dump_dir}',
        '-q',
    ])

    # 第二步：用 -T json 拿 request metadata（method, full_uri, host, status, time）
    # 把所有 frame 当成单 packet JSON 输出，含 http 和 http2 两种
    json_text = _run_tshark([
        '-r', str(pcap_path),
        '-o', f'tls.keylog_file:{keys_path}',
        '-Y',
        '(http.request) or (http.response) or '
        '(http2.headers.method) or (http2.headers.status)',
        '-T', 'json',
        '--no-duplicate-keys',
    ])
    if not json_text.strip():
        return []
    try:
        packets = json.loads(json_text)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"⚠️ JSON parse 失败: {e}\n")
        return []

    # 收集所有 request 和 response，再两两匹配
    requests = []   # {timestamp, method, url, host, path, query, headers, stream_id, tcp_stream}
    responses = []  # {timestamp, status, host, path, query, headers, body_path, stream_id, tcp_stream, response_for_uri}

    for pkt in packets:
        try:
            layers = pkt.get('_source', {}).get('layers', {})
            frame = layers.get('frame', {})
            ts = frame.get('frame.time_epoch', '')
            tcp = layers.get('tcp', {})
            tcp_stream = tcp.get('tcp.stream', '')

            # HTTP/1.1
            http_layer = layers.get('http')
            if isinstance(http_layer, dict):
                _consume_http1_layer(http_layer, requests, responses, ts, tcp_stream)
            elif isinstance(http_layer, list):
                for h in http_layer:
                    _consume_http1_layer(h, requests, responses, ts, tcp_stream)

            # HTTP/2
            http2 = layers.get('http2')
            if http2:
                _consume_http2_layer(http2, requests, responses, ts, tcp_stream)
        except Exception:
            continue

    # 把每个 dump 文件的内容读出来 → 配对
    pairs = []
    pair_index = 0

    # 优先按 (tcp_stream + stream_id) 匹配 (HTTP/2)，按 (tcp_stream) 匹配 (HTTP/1.1)
    # 简化：按 timestamp 顺序，请求和最近的同 host+path 响应配对

    for resp in responses:
        # 找匹配 request
        req = _match_request_for_response(resp, requests)
        if req is None:
            continue
        body_bytes = b''
        # 通过 dump_dir 找对应 body 文件
        body_file = _find_body_file(dump_dir, resp.get('path', ''), resp.get('query', ''),
                                    resp.get('host', ''), pair_index)
        if body_file is not None:
            try:
                body_bytes = body_file.read_bytes()
            except OSError:
                pass

        pair = {
            'timestamp': resp.get('timestamp', ''),
            'method': req.get('method', 'GET'),
            'url': req.get('url', ''),
            'host': req.get('host', ''),
            'path': req.get('path', ''),
            'query': req.get('query', {}),
            'request_headers': req.get('headers', {}),
            'request_body': req.get('body_text', ''),
            'response_status': resp.get('status', 200),
            'response_headers': resp.get('headers', {}),
            'response_body': body_bytes,
            'tcp_stream': req.get('tcp_stream', ''),
            'stream_id': req.get('stream_id', ''),
        }
        pairs.append(pair)
        pair_index += 1

    # 兜底：扫 dump 文件夹里没匹配上的目标 API 文件
    pair_paths = {p['path'] + '?' + (p['query'] if isinstance(p['query'], str) else '') for p in pairs}
    for f in dump_dir.iterdir():
        if not f.is_file():
            continue
        name = f.name
        # tshark 把 ? 编码成 %3f，把它还原
        decoded = name.replace('%3f', '?')
        if any(kw in decoded.lower() for kw in API_KEYWORDS):
            # 已经处理过的跳过
            already = False
            for p in pairs:
                if p['response_body'] and len(p['response_body']) == f.stat().st_size:
                    already = True
                    break
            if already:
                continue
            # 没匹配上 metadata 的文件：用文件名构造伪 metadata
            try:
                body = f.read_bytes()
                # 文件名 = path + query（无 protocol/host）
                if '?' in decoded:
                    path_part, query_part = decoded.split('?', 1)
                else:
                    path_part, query_part = decoded, ''
                # 推断 host：catfront / mapi / m.dianping
                if 'review' in path_part.lower() or 'shopaggregatedump' in path_part.lower():
                    host = 'mapi.dianping.com'
                elif 'wxsearch' in path_part.lower() or 'search' in path_part.lower():
                    host = 'm.dianping.com'
                elif 'metric' in path_part.lower() or 'speed' in path_part.lower():
                    host = 'catfront.dianping.com'
                else:
                    host = 'mapi.dianping.com'
                # 构造完整 url
                if not path_part.startswith('/'):
                    if 'review' in path_part:
                        path_part = '/mapi/review/' + path_part
                    elif 'shopaggregatedump' in path_part:
                        path_part = '/dpcategory/' + path_part
                    else:
                        path_part = '/mapi/' + path_part
                full_url = f'https://{host}{path_part}'
                if query_part:
                    full_url += '?' + query_part
                query_dict = {k: v[0] if v else '' for k, v in parse_qs(query_part).items()}
                pair = {
                    'timestamp': datetime.now().isoformat(timespec='seconds'),
                    'method': 'GET',
                    'url': full_url,
                    'host': host,
                    'path': path_part,
                    'query': query_dict,
                    'request_headers': {},
                    'request_body': '',
                    'response_status': 200,
                    'response_headers': {'content-type': 'application/json'},
                    'response_body': body,
                    'tcp_stream': '',
                    'stream_id': '',
                    '_recovered_from_filename': True,
                }
                pairs.append(pair)
            except OSError:
                pass

    return pairs


def _safe(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def _consume_http1_layer(http_layer: dict, requests: list, responses: list,
                         ts: str, tcp_stream: str):
    if not isinstance(http_layer, dict):
        return
    # HTTP/1.1 一个 packet 通常包含一个 request 或一个 response
    if any(k.startswith('http.request') for k in http_layer):
        method = _safe(http_layer, 'http.request.method', default='GET')
        full_uri = _safe(http_layer, 'http.request.full_uri',
                         default=_safe(http_layer, 'http.request.uri', default=''))
        host = _safe(http_layer, 'http.host', default='')
        # 解析 url
        url_for_parse = full_uri if full_uri.startswith('http') else f'https://{host}{full_uri}'
        parsed = urlparse(url_for_parse)
        # 提取 headers
        headers = _http1_headers_from_layer(http_layer)
        body_text = _safe(http_layer, 'http.file_data', default='') or ''
        requests.append({
            'timestamp': ts,
            'method': method,
            'url': url_for_parse,
            'host': host or parsed.netloc,
            'path': parsed.path,
            'query': {k: v[0] if v else '' for k, v in parse_qs(parsed.query).items()},
            'headers': headers,
            'body_text': body_text,
            'tcp_stream': tcp_stream,
            'stream_id': '',
        })
    if any(k.startswith('http.response') for k in http_layer):
        status = _safe(http_layer, 'http.response.code', default='200')
        try:
            status = int(str(status))
        except ValueError:
            status = 200
        # http.response_for.uri 给我们对应的请求 URI
        resp_for = _safe(http_layer, 'http.response_for.uri', default='')
        host = _safe(http_layer, 'http.host', default='')
        parsed = urlparse(resp_for) if resp_for else None
        headers = _http1_headers_from_layer(http_layer)
        responses.append({
            'timestamp': ts,
            'status': status,
            'host': host or (parsed.netloc if parsed else ''),
            'path': parsed.path if parsed else '',
            'query': parsed.query if parsed else '',
            'headers': headers,
            'tcp_stream': tcp_stream,
            'stream_id': '',
            'response_for_uri': resp_for,
        })


def _http1_headers_from_layer(http_layer: dict) -> Dict[str, str]:
    headers = {}
    for k, v in http_layer.items():
        if not isinstance(k, str):
            continue
        # http.host, http.user_agent, ... 这些就是 header
        if k.startswith('http.') and k.count('.') >= 1 and not k.startswith('http.request') and not k.startswith('http.response'):
            short = k[len('http.'):]
            if isinstance(v, str):
                headers[short] = v
    return headers


def _consume_http2_layer(http2_layer, requests: list, responses: list,
                         ts: str, tcp_stream: str):
    """http2 layer 可能是 dict（含 http2.stream 字段）或 list（多个 frame）。"""
    if isinstance(http2_layer, list):
        for h2 in http2_layer:
            _consume_http2_layer(h2, requests, responses, ts, tcp_stream)
        return
    if not isinstance(http2_layer, dict):
        return
    streams = http2_layer.get('http2.stream')
    if streams is None:
        return
    if isinstance(streams, dict):
        streams = [streams]
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        stream_id = stream.get('http2.streamid', '')
        frame_type = stream.get('http2.type', '')
        # HEADERS frame
        if frame_type == '1':
            headers = _h2_headers(stream)
            if not headers:
                continue
            if ':status' in headers:
                # response
                try:
                    status = int(headers[':status'])
                except ValueError:
                    status = 200
                responses.append({
                    'timestamp': ts,
                    'status': status,
                    'host': '',
                    'path': '',
                    'query': '',
                    'headers': headers,
                    'tcp_stream': tcp_stream,
                    'stream_id': stream_id,
                    'response_for_uri': '',
                })
            elif ':path' in headers:
                method = headers.get(':method', 'GET')
                authority = headers.get(':authority', '')
                path = headers.get(':path', '')
                scheme = headers.get(':scheme', 'https')
                full_url = f"{scheme}://{authority}{path}" if authority else path
                parsed = urlparse(full_url)
                requests.append({
                    'timestamp': ts,
                    'method': method,
                    'url': full_url,
                    'host': authority,
                    'path': parsed.path,
                    'query': {k: v[0] if v else '' for k, v in parse_qs(parsed.query).items()},
                    'headers': headers,
                    'body_text': '',
                    'tcp_stream': tcp_stream,
                    'stream_id': stream_id,
                })


def _h2_headers(stream: dict) -> Dict[str, str]:
    headers = {}
    h = stream.get('http2.header')
    if isinstance(h, dict):
        h = [h]
    if not isinstance(h, list):
        return headers
    for entry in h:
        if not isinstance(entry, dict):
            continue
        name = entry.get('http2.header.name', '')
        val = entry.get('http2.header.value', '')
        if name:
            headers[name] = val
    return headers


def _match_request_for_response(resp: dict, requests: list) -> Optional[dict]:
    """根据 tcp_stream + stream_id 或 response_for_uri 匹配 request。"""
    # HTTP/2: tcp_stream + stream_id
    if resp.get('stream_id'):
        for req in requests:
            if (req.get('tcp_stream') == resp.get('tcp_stream') and
                req.get('stream_id') == resp.get('stream_id')):
                return req
    # HTTP/1.1: response_for_uri 直接给
    if resp.get('response_for_uri'):
        for req in requests:
            if req.get('url') == resp['response_for_uri']:
                return req
    # HTTP/1.1 兜底：tcp_stream + 时序（该 stream 上最近的未匹配 request）
    if resp.get('tcp_stream'):
        candidates = [r for r in requests if r.get('tcp_stream') == resp['tcp_stream']]
        if candidates:
            return candidates[-1]
    return None


def _find_body_file(dump_dir: Path, path: str, query, host: str, idx: int) -> Optional[Path]:
    """尝试从 dump_dir 找匹配响应的 body 文件。
    tshark --export-objects http 文件名 = path 最后段 + ?query 的编码版本"""
    if not path:
        return None
    last_seg = path.rsplit('/', 1)[-1]
    if not last_seg:
        return None
    # 候选模式: 文件名以 last_seg 开头
    candidates = sorted([f for f in dump_dir.iterdir()
                         if f.is_file() and f.name.lower().startswith(last_seg.lower())])
    if not candidates:
        return None
    # 如果 query 含 shopuuid 或 keyword，挑选含同样字符串的文件
    query_str = query if isinstance(query, str) else (
        '&'.join(f"{k}={v}" for k, v in query.items()) if isinstance(query, dict) else '')
    if query_str:
        # 看文件名包含特定 query value
        m = re.search(r'shopuuid=([A-Za-z0-9_-]+)', query_str)
        if m:
            shopuuid = m.group(1)
            for f in candidates:
                if shopuuid in f.name:
                    return f
        m = re.search(r'keyword=([^&]+)', query_str)
        if m:
            kw = m.group(1)
            for f in candidates:
                if kw in f.name:
                    return f
    if idx < len(candidates):
        return candidates[idx]
    return candidates[0]


# ----------------------------------------------------------------------
# 把 pair 喂给 dianping_interceptor
# ----------------------------------------------------------------------

class _FakeRequest:
    def __init__(self, url, method, headers, body_text, query):
        self.url = url
        self.method = method
        self.headers = headers
        self.text = body_text
        self.query = query if isinstance(query, dict) else {}


class _FakeResponse:
    def __init__(self, status, headers, text):
        self.status_code = status
        self.headers = headers
        self.text = text


class _FakeFlow:
    def __init__(self, req, resp):
        self.request = req
        self.response = resp


def _decompress_body(body: bytes, encoding: str) -> bytes:
    encoding = (encoding or '').lower()
    if 'gzip' in encoding:
        import gzip
        try:
            return gzip.decompress(body)
        except Exception:
            return body
    if 'deflate' in encoding:
        import zlib
        try:
            return zlib.decompress(body)
        except Exception:
            try:
                return zlib.decompress(body, -zlib.MAX_WBITS)
            except Exception:
                return body
    if 'br' in encoding:
        try:
            import brotli
            return brotli.decompress(body)
        except Exception:
            return body
    return body


def dispatch_pair_to_interceptor(pair: Dict[str, Any]) -> bool:
    url = pair.get('url') or ''
    if not url:
        return False
    if not any(kw in url.lower() for kw in API_KEYWORDS):
        return False

    method = pair.get('method', 'GET')
    req_headers = {k.lstrip(':'): v for k, v in pair.get('request_headers', {}).items()}
    req_body = pair.get('request_body', '')
    if isinstance(req_body, bytes):
        req_body = req_body.decode('utf-8', errors='replace')

    resp_headers = {k.lstrip(':'): v for k, v in pair.get('response_headers', {}).items()}
    resp_body = pair.get('response_body', b'')
    if isinstance(resp_body, str):
        resp_body = resp_body.encode('utf-8', errors='replace')

    encoding = (resp_headers.get('content-encoding') or '').lower()
    resp_body = _decompress_body(resp_body, encoding)
    resp_text = resp_body.decode('utf-8', errors='replace')

    fake_req = _FakeRequest(url, method, req_headers, req_body, pair.get('query', {}))
    fake_resp = _FakeResponse(pair.get('response_status', 200), resp_headers, resp_text)
    fake_flow = _FakeFlow(fake_req, fake_resp)

    try:
        dpi.response(fake_flow)
        return True
    except Exception as e:
        sys.stderr.write(f"⚠️ interceptor.response 异常: {e}\n")
        return False


# ----------------------------------------------------------------------
# 离线模式
# ----------------------------------------------------------------------

def run_offline(pcap_path: Path, keys_path: Path) -> int:
    if not pcap_path.exists():
        sys.stderr.write(f"❌ pcap 不存在: {pcap_path}\n")
        return 1
    if not keys_path.exists():
        sys.stderr.write(f"❌ keys 不存在: {keys_path}\n")
        return 1

    print(f"📦 解析 {pcap_path}  (size={pcap_path.stat().st_size} bytes)")
    pairs = extract_http_pairs(pcap_path, keys_path)
    print(f"  抽取出 {len(pairs)} 个 HTTP 请求/响应对")
    if not pairs:
        return 2

    n = 0
    for pair in pairs:
        url = pair.get('url', '')
        host = pair.get('host', '')
        path = pair.get('path', '')
        # 如果 host 是 catfront 跳过（噪音）
        if host == 'catfront.dianping.com':
            continue
        if any(kw in url.lower() for kw in API_KEYWORDS):
            ok = dispatch_pair_to_interceptor(pair)
            tag = '✅' if ok else '⚠️'
            print(f"  {tag} {pair['method']} {host}{path[:80]} -> HTTP {pair['response_status']} ({len(pair['response_body'])} bytes)")
            if ok:
                n += 1
        else:
            # 显示其它请求作为调试
            print(f"     {pair['method']} {host}{path[:80]} -> HTTP {pair['response_status']}")
    print(f"\n📊 处理 {n} 个目标 API 请求/响应对")
    return 0 if n > 0 else 2


# ----------------------------------------------------------------------
# 实时模式
# ----------------------------------------------------------------------

def run_live(iface: str, keys_path: Path, capture_dir: Path,
             rotate_seconds: int = 5) -> int:
    """实时模式：tshark ringbuffer 抓包，定期解析新 pcap。"""
    capture_dir.mkdir(parents=True, exist_ok=True)
    bpf = 'tcp port 443'

    pcap_template = str(capture_dir / 'live_%Y%m%d_%H%M%S.pcap')
    cmd = [
        'tshark',
        '-i', iface,
        '-f', bpf,
        '-w', pcap_template,
        '-b', f'duration:{rotate_seconds}',
    ]
    print(f"🚀 实时模式: {' '.join(cmd)}")
    print(f"   keys: {keys_path}")
    print(f"   ring: {capture_dir}/")

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    processed = set()

    try:
        while True:
            time.sleep(rotate_seconds + 1)
            files = sorted(capture_dir.glob('live_*.pcap'))
            if len(files) <= 1:
                continue
            for pcap in files[:-1]:
                if pcap in processed:
                    continue
                processed.add(pcap)
                if pcap.stat().st_size < 200:
                    pcap.unlink(missing_ok=True)
                    continue
                try:
                    pairs = extract_http_pairs(pcap, keys_path)
                    for pair in pairs:
                        if pair.get('host') == 'catfront.dianping.com':
                            continue
                        if any(kw in pair.get('url', '').lower() for kw in API_KEYWORDS):
                            ok = dispatch_pair_to_interceptor(pair)
                            if ok:
                                print(f"  📥 [{datetime.now():%H:%M:%S}] {pair['method']} "
                                      f"{pair['host']}{pair['path'][:60]} -> {pair['response_status']}")
                except Exception as e:
                    sys.stderr.write(f"⚠️ 处理 {pcap.name} 失败: {e}\n")
                # 解析完释放空间
                try:
                    pcap.unlink()
                except OSError:
                    pass
    except KeyboardInterrupt:
        print("\n⏹️ 中断")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def main():
    _check_tshark()
    ap = argparse.ArgumentParser()
    ap.add_argument('--pcap', type=Path, help='离线模式：分析现有 pcap 文件')
    ap.add_argument('--keys', type=Path, default=Path('/tmp/wx_keys.log'))
    ap.add_argument('--live', action='store_true', help='实时模式')
    ap.add_argument('--iface', default='wlp2s0', help='实时模式网卡')
    ap.add_argument('--capture-dir', type=Path, default=Path('/tmp/wx_capture_live'))
    ap.add_argument('--rotate', type=int, default=5, help='实时模式 pcap 旋转秒数')
    args = ap.parse_args()

    if args.live:
        return run_live(args.iface, args.keys, args.capture_dir, args.rotate)
    elif args.pcap:
        return run_offline(args.pcap, args.keys)
    else:
        ap.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(main())
