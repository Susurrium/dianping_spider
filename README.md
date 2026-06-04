# Dianping Spider

大众点评 / 美团微信小程序评论抓取与导出工具。当前主流程以 PC 微信小程序抓包为核心：`mitmdump` 负责捕获评论 API，`run.py` 负责辅助滚动评价页并按门店写入 JSON。

本仓库基于开源大众点评爬虫思路继续改造，重点支持：

- 大众点评微信小程序评论自动抓取
- 每家店单独保存评论 JSON
- 评论发布时间、发布人、评论文本、顾客评分字段
- 美团微信小程序抓包、门店 ID 解析和评论导出
- Excel 门店清单驱动的批量采集
- Linux 桌面微信 + mitmproxy + xdotool 的半自动工作流

仅限学习、研究和内部数据分析。请遵守平台服务条款、当地法律法规和数据合规要求，不要用于未授权、商用或高频压测场景。

## 项目状态

推荐入口是：

```bash
python3 run.py
```

美团入口是：

```bash
python3 run.py --platform meituan
```

历史脚本较多，根目录下的 `main.py`、`go.py`、`grab.py` 等保留为旧流程或实验工具。新用户优先看 `run.py`、`start_mitm.sh`、`mitm_dianping.py`、`review_exporter.py` 和 `docs/meituan_miniapp.md`。

## 目录结构

```text
.
├── run.py                         # 当前主入口：交互选择门店、自动滚动评价页
├── start_mitm.sh                  # Linux/GNOME 下启动 mitmdump + 微信 + 系统代理
├── stop_mitm.sh                   # 停止 mitmdump/微信并恢复系统代理
├── mitm_dianping.py               # mitmdump addon，直接写 output/store_reviews/*.json
├── dianping_interceptor.py        # 通用小程序 API 抓包解析器
├── review_exporter.py             # 从 mitm_logs 导出分析用评论 JSON
├── meituan_miniapp_interceptor.py # 美团微信小程序独立抓包入口
├── meituan_shop_id_resolver.py    # 从美团抓包解析门店 ID
├── meituan_review_exporter.py     # 导出美团评论
├── 门店抽样.xlsx                  # 默认门店清单之一
├── mitm_logs/                     # 抓包日志和样本
├── output/                        # 抓取输出
├── tests/                         # 可自动运行的单元测试
└── docs/                          # 补充说明
```

## 输出格式

大众点评主流程会写入：

```text
output/store_reviews/<编号>_<门店名>.json
```

单条评论结构示例：

```json
{
  "门店": "达美乐比萨(示例店)",
  "发布时间": "6月1日",
  "发布人": "用户昵称",
  "顾客评分": "5",
  "评分": "5",
  "文字": "评论正文"
}
```

说明：

- `顾客评分` / `评分` 是同一份顾客星级字段，保留两个名字是为了兼容后续清洗脚本。
- 部分旧文件可能没有评分字段；重新抓到同一条评论后，`mitm_dianping.py` 会尽量回填评分。
- 如果平台接口没有返回评分，字段会是空字符串。

## Excel 门店清单

默认读取：

```text
门店抽样.xlsx
```

如果不存在，会回退到：

```text
达美乐_门店.xlsx
```

`review_exporter.py` 读取 Excel 时默认从第 3 行开始，B 列是门店名，C 列是地址。门店名会用于输出文件命名和门店匹配。

## Linux 配置

Linux 是目前支持最完整的运行环境，尤其是自动滚动和微信窗口控制。

推荐环境：

- Ubuntu 22.04/24.04 或其他 GNOME/X11 桌面
- Python 3.9+
- PC 微信 Linux 版
- mitmproxy / mitmdump
- xdotool
- 可用代理，例如本项目脚本默认的 Clash `127.0.0.1:7890`

安装依赖：

```bash
cd /home/hetaisheng/dianping_spider

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
pip install mitmproxy pytest

sudo apt update
sudo apt install -y xdotool
```

首次安装 mitmproxy 证书：

```bash
mitmproxy
```

然后在微信或系统浏览器打开：

```text
http://mitm.it
```

按 mitmproxy 页面提示安装并信任证书。证书未安装时，微信小程序 HTTPS 流量通常无法正常解密。

### 大众点评抓取流程

启动 mitm 和微信：

```bash
bash start_mitm.sh
```

脚本会做这些事：

- 启动 `mitmdump`，监听 `8080`
- 上游代理转发到 `127.0.0.1:7890`
- 把 GNOME 系统代理临时切到 `127.0.0.1:8080`
- 启动 Linux 微信

接着在微信里操作：

1. 扫码登录微信
2. 打开大众点评小程序
3. 搜索并进入目标门店
4. 打开评价页

然后运行：

```bash
python3 run.py
```

交互示例：

```text
🎯 最终版 | 335家店
  风险档: fast(快) / balanced(默认) / safe(稳)
  list=进度 | q=退出

🎯 编号 [balanced]: 97
  达美乐比萨(天河购书中心店) (已有14条)
  评论数 (回车=自动):
  确认在评价页 Enter...
   +14 +14 · +12 [到底]
  ✅ +40 → 总54 | 6轮 18s
```

常用输入：

- `list`：查看前 60 家门店进度
- `fast`：更快，风险更高
- `balanced`：默认档
- `safe`：更慢，更稳
- `q`：退出
- 输入数字，例如 `97`：抓取第 97 家门店

结束后恢复代理和关闭微信：

```bash
bash stop_mitm.sh
```

实时查看 mitmdump 输出：

```bash
tail -f /tmp/mitm_capture.log
tail -f /tmp/mitmdump_out.log
```

## Windows 配置

Windows 可以运行解析、导出和手动抓包流程；完整自动滚动依赖 `xdotool`，因此不直接支持 Windows 原生桌面自动滚动。

推荐安装：

- [Python](https://www.python.org/downloads/)
- [Git for Windows](https://git-scm.com/download/win)
- [mitmproxy](https://mitmproxy.org/)
- Windows 版微信

安装依赖：

```powershell
cd C:\path\to\dianping_spider

py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install mitmproxy pytest
```

手动抓包建议：

1. 启动 `mitmdump`，监听 `8080`
2. Windows 系统代理设置为 `127.0.0.1:8080`
3. 微信里打开大众点评或美团小程序
4. 手动进入门店评价页并滚动
5. 用 `review_exporter.py` 或美团导出脚本处理 `mitm_logs/`

示例：

```powershell
mitmdump -s dianping_interceptor.py -p 8080
python review_exporter.py
```

如果需要和 Linux 主流程完全一致，建议使用 Linux 实机或虚拟机运行微信桌面端和 `xdotool`。

## macOS 配置

macOS 可以运行解析、导出和手动抓包流程；自动滚动脚本目前没有适配 AppleScript 或 Accessibility API。

推荐安装：

- [Homebrew](https://brew.sh/)
- [Python](https://www.python.org/downloads/macos/)
- [mitmproxy](https://mitmproxy.org/)
- macOS 版微信

安装依赖：

```bash
brew install python mitmproxy

cd /path/to/dianping_spider
python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
pip install pytest
```

手动抓包流程：

1. 启动 `mitmdump -s dianping_interceptor.py -p 8080`
2. 在系统网络设置里把 HTTP/HTTPS 代理设为 `127.0.0.1:8080`
3. 安装 mitmproxy 证书并设为信任
4. 微信里进入小程序评价页并手动滚动
5. 运行导出脚本

示例：

```bash
python3 review_exporter.py --log-dir mitm_logs --output output/domino_reviews.json
```

## Docker 配置

Docker 适合跑解析、导出、测试和无界面的 mitmproxy 服务。不建议把 Docker 当作完整自动抓取环境，因为桌面微信、系统代理、窗口定位和 `xdotool` 都依赖宿主机图形环境。

### 方式一：直接使用官方 Python 镜像

Linux/macOS：

```bash
cd /home/hetaisheng/dianping_spider

docker run --rm -it \
  -v "$PWD":/app \
  -w /app \
  python:3.10-slim bash
```

容器内执行：

```bash
apt-get update
apt-get install -y gcc libxml2-dev libxslt1-dev zlib1g-dev
pip install --upgrade pip
pip install -r requirements.txt
pip install mitmproxy pytest
python3 review_exporter.py
```

Windows PowerShell：

```powershell
docker run --rm -it -v ${PWD}:/app -w /app python:3.10-slim bash
```

### 方式二：Docker 运行 mitmdump

Linux 下如果宿主机微信可以访问容器监听端口，可以运行：

```bash
docker run --rm -it --network host \
  -v "$PWD":/app \
  -w /app \
  python:3.10-slim bash
```

容器内：

```bash
apt-get update
apt-get install -y gcc libxml2-dev libxslt1-dev zlib1g-dev
pip install -r requirements.txt mitmproxy
mitmdump -s dianping_interceptor.py -p 8080
```

然后把宿主机系统代理设置到：

```text
127.0.0.1:8080
```

注意：

- Docker Desktop for macOS/Windows 不支持完全等价的 `--network host` 行为。
- 容器里的 mitmproxy 证书需要和宿主机微信信任链对应。
- 自动滚动仍然应在宿主机执行，而不是容器内执行。

## 美团微信小程序

美团不复用大众点评自动滚动主循环，当前是独立抓包、解析、导出流程。

启动美团抓包：

```bash
mitmdump --listen-port 9092 --set ssl_insecure=true \
  -s /home/hetaisheng/dianping_spider/meituan_miniapp_interceptor.py
```

微信里打开独立美团小程序，搜索门店、进入门店页、打开评论页并滚动。

解析门店 ID：

```bash
python3 meituan_shop_id_resolver.py --excel 门店抽样.xlsx
```

导出评论：

```bash
python3 meituan_review_exporter.py --excel 门店抽样.xlsx
```

输出：

```text
output/meituan_reviews.json
output/meituan_store_reviews/*.json
mitm_logs/meituan/
```

更详细说明见 [docs/meituan_miniapp.md](./docs/meituan_miniapp.md)。

## 离线导出

如果已经有 `mitm_logs/`，可以不打开微信，直接导出：

```bash
python3 review_exporter.py \
  --log-dir mitm_logs \
  --output output/domino_reviews.json \
  --per-store-dir output/store_reviews
```

美团离线导出：

```bash
python3 meituan_review_exporter.py \
  --log-dir mitm_logs/meituan \
  --output output/meituan_reviews.json \
  --per-store-dir output/meituan_store_reviews
```

## 测试

推荐跑当前可自动运行的核心测试子集：

```bash
pytest -q \
  tests/test_auto_shop_uuid_resolver.py \
  tests/test_dianping_events.py \
  tests/test_meituan_entrypoints.py \
  tests/test_meituan_local_log_discover.py \
  tests/test_mitm_dianping.py \
  tests/test_review_exporter.py
```

不要直接跑全量 `pytest`。根目录下有一些历史交互脚本以 `test_*.py` 命名，例如 `test_scroll.py` 会在导入时查找微信窗口；`tests/` 里也保留了少量历史坏编码/空字节文件，后续需要单独清理。

如果只是为了推送远端并跳过本机 pre-push 钩子：

```bash
ECC_SKIP_PREPUSH=1 git push
```

## 常见问题

### 报错：没找到微信窗口

确认 Linux 微信已经启动，并且不是最小化状态。`run.py` 需要通过窗口定位和 `xdotool` 把滚动事件发送到评价页。

### 报错：mitmdump 没在跑

先运行：

```bash
bash start_mitm.sh
```

或者手动启动：

```bash
mitmdump -s mitm_dianping.py -p 8080
```

### 抓不到 HTTPS 内容

通常是 mitmproxy 证书没有安装或未信任。打开 `http://mitm.it`，按系统提示安装证书。

### 输出 JSON 变成 0 条

检查目标文件是否为空文件或损坏：

```bash
ls -lh output/store_reviews/
```

新版本写入时使用临时文件替换，降低 0 字节文件风险。若旧文件已损坏，可以先备份后删除，再重新抓取。

### 响应变慢或连续没有新增

可能是到达底部，也可能是限流。建议切换 `safe` 档，或换店前等待 1-2 分钟。

## 安全与隐私

`mitm_logs/` 可能包含请求头、cookie、token、门店样本和用户评论内容。公开提交 PR 前请先脱敏，尤其注意：

- `captured_credentials.json`
- `wx_credentials.json`
- 原始抓包响应
- 任何 cookie、token、手机号或个人信息

本仓库当前允许保存样本日志是为了复现和离线解析；公开协作时请只提交必要的最小样本。

## 贡献

欢迎提交 issue 和 PR。比较适合贡献的方向：

- 美团评论端到端样本和解析适配
- Windows/macOS 桌面自动滚动适配
- 更稳的门店匹配和去重逻辑
- 评论评分、子评分、图片、标签字段解析
- 更干净的测试集和 CI 配置
- Dockerfile / Compose 的生产化封装

提交 PR 前建议：

```bash
pytest -q \
  tests/test_auto_shop_uuid_resolver.py \
  tests/test_dianping_events.py \
  tests/test_meituan_entrypoints.py \
  tests/test_meituan_local_log_discover.py \
  tests/test_mitm_dianping.py \
  tests/test_review_exporter.py
```

如果改动涉及抓包解析，请附上脱敏后的最小 JSON 样本和预期输出。

## 相关链接

- [Python](https://www.python.org/)
- [mitmproxy](https://mitmproxy.org/)
- [Docker](https://www.docker.com/)
- [Git](https://git-scm.com/)
- [GitHub Personal Access Tokens](https://github.com/settings/tokens)
- [微信官网](https://weixin.qq.com/)
- [项目美团说明](./docs/meituan_miniapp.md)
- [数据字段说明](./docs/data.md)
- [常见问题旧文档](./docs/problems.md)

## License

本项目遵守 [GPL-3.0](./LICENSE)。
