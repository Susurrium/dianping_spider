# Dianping Spider

大众点评 / 美团微信小程序评论采集与导出工具。项目通过 PC 微信小程序流量抓包获取评论接口响应，再按门店输出结构化 JSON，适合门店评论分析、服务质量追踪和离线数据清洗。

> 仅限学习、研究和合法授权的数据分析。请遵守平台服务条款、隐私合规要求和当地法律法规。

## 功能概览

| 能力 | 大众点评 | 美团 |
| --- | --- | --- |
| 微信小程序抓包 | 支持 | 支持 |
| 评论文本导出 | 支持 | 支持 |
| 评论发布时间 | 支持 | 支持，取决于接口字段 |
| 评论发布人 | 支持 | 支持，取决于接口字段 |
| 顾客评分 | 支持 | 支持，取决于接口字段 |
| 每店单独 JSON | 支持 | 支持 |
| Excel 门店清单匹配 | 支持 | 支持 |
| 自动滚动评价页 | Linux/X11 支持 | 尚未独立实现 |

当前推荐入口：

```bash
python3 run.py
```

美团入口会打印当前美团抓包、解析、导出流程：

```bash
python3 run.py --platform meituan
```

## 工作原理

```text
PC 微信小程序
    ↓ 读取系统代理
mitmproxy / mitmdump
    ↓ 解密并解析小程序 API 响应
mitm_dianping.py / dianping_interceptor.py
    ↓ 去重、字段抽取、门店匹配
output/*.json
```

大众点评主流程由两部分组成：

- `mitm_dianping.py`：mitmdump addon，监听评论 API，抽取 `门店`、`发布时间`、`发布人`、`顾客评分`、`评分`、`文字`。
- `run.py`：读取 Excel 门店列表，交互选择门店，通过 `xdotool` 滚动当前微信评价页，等待抓包结果写入文件。

由于小程序请求通常带签名和设备参数，本项目不伪造评论接口请求，而是让微信客户端真实触发 API，再从抓包响应中解析数据。

## 目录说明

```text
run.py                         # 主入口：门店选择、风险档、自动滚动
start_mitm.sh                  # Linux/GNOME 快速启动 mitmdump + 微信 + 系统代理
stop_mitm.sh                   # 停止 mitmdump/微信并恢复代理
mitm_dianping.py               # 大众点评评论抓包写入器
dianping_interceptor.py        # 通用小程序 API 捕获和日志写入
review_exporter.py             # 从 mitm_logs 离线导出大众点评评论
meituan_miniapp_interceptor.py # 美团独立小程序抓包入口
meituan_shop_id_resolver.py    # 美团门店 ID 解析
meituan_review_exporter.py     # 美团评论导出
docs/meituan_miniapp.md        # 美团增量支持说明
tests/                         # 部分可自动运行的单元测试
```

根目录保留了部分历史实验脚本。新用户优先使用上表中的入口，避免直接从旧脚本开始接入。

## 数据输出

大众点评主流程输出：

```text
output/store_reviews/<编号>_<门店名>.json
```

美团导出输出：

```text
output/meituan_reviews.json
output/meituan_store_reviews/*.json
```

单条评论示例：

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

字段说明：

| 字段 | 说明 |
| --- | --- |
| `门店` | Excel 中匹配到的门店名称 |
| `发布时间` | 平台返回的展示时间或可解析日期 |
| `发布人` | 用户昵称，取决于接口字段 |
| `顾客评分` | 单条评论的顾客评分，常见值如 `5`、`4`、`3.5` |
| `评分` | 与 `顾客评分` 保持一致，兼容旧清洗脚本 |
| `文字` | 评论正文 |

## Excel 门店清单

默认门店文件：

```text
门店抽样.xlsx
```

如果不存在，`run.py` 会回退到：

```text
达美乐_门店.xlsx
```

`review_exporter.py` 读取 Excel 时默认从第 3 行开始，B 列为门店名称，C 列为地址。美团相关脚本支持通过 `--excel` 指定文件：

```bash
python3 meituan_shop_id_resolver.py --excel 门店抽样.xlsx
python3 meituan_review_exporter.py --excel 门店抽样.xlsx
```

## 环境矩阵

| 环境 | 支持状态 | 说明 |
| --- | --- | --- |
| Linux + X11/GNOME | 推荐 | 支持 `start_mitm.sh` 和 `xdotool` 自动滚动 |
| Windows | 部分支持 | 可运行解析和手动抓包；自动滚动需自行适配 |
| macOS | 部分支持 | 可运行解析和手动抓包；自动滚动需自行适配 |
| Docker | 部分支持 | 适合解析、导出、测试、无界面 mitmdump；不适合直接控制桌面微信 |

## Linux 安装

安装系统依赖：

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip xdotool
```

创建 Python 环境：

```bash
git clone https://github.com/HUST-hetaisheng/dianping_spider.git
cd dianping_spider

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
pip install mitmproxy pytest
```

安装并信任 mitmproxy 证书：

```bash
mitmproxy
```

保持 mitmproxy 运行时，在浏览器或微信内打开：

```text
http://mitm.it
```

下载对应系统证书并设为信任。证书未正确安装时，只能看到 CONNECT 流量，无法解析 HTTPS 响应内容。

## Linux 大众点评抓取

`start_mitm.sh` 适用于 GNOME 系统代理和 Linux 微信 AppImage 场景。启动前可按需设置环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MITM_PORT` | `8080` | mitmdump 监听端口 |
| `CLASH_PORT` | `7890` | Clash HTTP 端口，用于默认上游代理和恢复代理 |
| `UPSTREAM_PROXY` | `http://127.0.0.1:${CLASH_PORT}` | 上游代理，例如 Clash |
| `WECHAT_PLATFORM` | `auto` | `auto`、`linux` 或 `windows`；WSL 下自动优先 Windows 微信 |
| `WECHAT_BIN` | 自动探测常见 AppImage 路径 | 微信可执行文件路径 |
| `WECHAT_WIN_EXE` | 自动探测常见 Windows 路径 | Windows 微信可执行文件路径，支持 `/mnt/c/...` 或 `C:\...` |

示例：

```bash
WECHAT_BIN=/opt/wechat/WeChatLinux_x86_64.AppImage \
CLASH_PORT=7890 \
bash start_mitm.sh
```

WSL 下使用 Windows 微信：

```bash
WECHAT_PLATFORM=windows \
WECHAT_WIN_EXE='/mnt/c/Program Files/Tencent/WeChat/WeChat.exe' \
CLASH_PORT=7890 \
bash restart_wechat_with_proxy.sh
```

启动后：

1. 微信扫码登录。
2. 打开大众点评小程序。
3. 进入目标门店评价页。
4. 回到终端运行主程序。

```bash
python3 run.py
```

交互命令：

| 输入 | 含义 |
| --- | --- |
| 数字，例如 `97` | 抓取第 97 家门店 |
| `list` | 查看前 60 家门店进度 |
| `fast` | 更快，限流风险更高 |
| `balanced` | 默认档 |
| `safe` | 更慢，更稳 |
| `q` | 退出 |

运行示例：

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

结束后恢复系统代理：

```bash
bash stop_mitm.sh
```

## Windows 配置

Windows 原生环境可用于手动抓包和离线导出。自动滚动依赖 Linux `xdotool`，默认不可用。

安装：

```powershell
git clone https://github.com/HUST-hetaisheng/dianping_spider.git
cd dianping_spider

py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install mitmproxy pytest
```

手动抓包：

```powershell
mitmdump -s dianping_interceptor.py -p 8080
```

然后在 Windows 网络代理中设置 HTTP/HTTPS 代理：

```text
127.0.0.1:8080
```

微信中进入门店评价页并手动滚动，抓包写入 `mitm_logs/` 后执行：

```powershell
python review_exporter.py
```

## macOS 配置

macOS 可用于手动抓包和离线导出。自动滚动未适配 AppleScript 或 Accessibility API。

安装：

```bash
brew install python mitmproxy git

git clone https://github.com/HUST-hetaisheng/dianping_spider.git
cd dianping_spider

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
pip install pytest
```

手动抓包：

```bash
mitmdump -s dianping_interceptor.py -p 8080
```

在系统网络设置中配置 HTTP/HTTPS 代理为 `127.0.0.1:8080`，安装并信任 mitmproxy 证书，然后在微信评价页手动滚动。

离线导出：

```bash
python3 review_exporter.py --log-dir mitm_logs --output output/domino_reviews.json
```

## Docker 配置

Docker 适合运行导出器、测试和无界面 mitmdump。桌面微信、系统代理切换和鼠标滚动仍应在宿主机完成。

运行解析环境：

```bash
docker run --rm -it \
  -v "$PWD":/app \
  -w /app \
  python:3.10-slim bash
```

容器内安装依赖：

```bash
apt-get update
apt-get install -y gcc libxml2-dev libxslt1-dev zlib1g-dev
pip install --upgrade pip
pip install -r requirements.txt
pip install mitmproxy pytest
```

导出已有抓包：

```bash
python3 review_exporter.py \
  --log-dir mitm_logs \
  --output output/domino_reviews.json \
  --per-store-dir output/store_reviews
```

Linux 下也可以让容器运行 mitmdump：

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

Docker Desktop on macOS/Windows 的 `--network host` 行为与 Linux 不完全一致，抓包端口暴露和证书信任需要单独处理。

## 美团微信小程序

美团抓包和大众点评隔离，默认只接收独立美团小程序 appid：

```text
wxde8ac0a21135c07d
```

启动抓包：

```bash
mitmdump --listen-port 9092 --set ssl_insecure=true \
  -s meituan_miniapp_interceptor.py
```

微信中打开美团小程序，搜索门店、进入门店页、打开评论页并滚动。

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
mitm_logs/meituan/
output/meituan/meituan_shop_id_map.json
output/meituan_reviews.json
output/meituan_store_reviews/
```

更多细节见 [docs/meituan_miniapp.md](./docs/meituan_miniapp.md)。

## 离线导出

大众点评：

```bash
python3 review_exporter.py \
  --excel 门店抽样.xlsx \
  --log-dir mitm_logs \
  --output output/domino_reviews.json \
  --per-store-dir output/store_reviews
```

美团：

```bash
python3 meituan_review_exporter.py \
  --excel 门店抽样.xlsx \
  --log-dir mitm_logs/meituan \
  --output output/meituan_reviews.json \
  --per-store-dir output/meituan_store_reviews
```

## 测试

当前可自动运行的核心测试：

```bash
pytest -q \
  tests/test_auto_shop_uuid_resolver.py \
  tests/test_dianping_events.py \
  tests/test_meituan_entrypoints.py \
  tests/test_meituan_local_log_discover.py \
  tests/test_mitm_dianping.py \
  tests/test_review_exporter.py
```

不要直接执行全量 `pytest`。仓库根目录保留了部分历史交互脚本，部分 `tests/` 文件也包含旧编码或空字节，需要后续清理。

## 常见问题

### `run.py` 提示没找到微信窗口

确认微信已经启动、窗口可见，并运行在 X11 环境。Wayland 环境下 `xdotool` 可能无法稳定控制窗口。

### `run.py` 提示 mitmdump 没在跑

先启动 mitmdump：

```bash
bash start_mitm.sh
```

或手动启动：

```bash
mitmdump -s mitm_dianping.py -p 8080
```

### 抓不到评论 API

优先检查：

1. 系统 HTTP/HTTPS 代理是否指向 mitmdump 端口。
2. mitmproxy 证书是否已安装并信任。
3. 微信是否在代理切换后重新启动。
4. 当前页面是否真的进入了门店评价页。

### 连续没有新增评论

可能已经到底，也可能触发限流。可切换 `safe` 档，或在跨店抓取前等待 1-2 分钟。

### 公开提交前如何处理日志

`mitm_logs/` 可能包含 cookie、token、请求头和用户内容。公开 PR 请只保留脱敏后的最小复现样本。

## 贡献

欢迎 issue 和 PR。优先欢迎以下方向：

- 美团评论接口真实样本和端到端适配
- Windows/macOS 自动滚动实现
- 评论评分、子评分、图片、标签字段解析
- Excel 门店匹配和重复评论合并改进
- 清理历史交互测试，建立稳定 CI
- Dockerfile / docker-compose 封装

提交 PR 前建议运行核心测试，并在 PR 描述中说明：

- 修改目的
- 影响入口
- 使用的测试命令
- 如涉及抓包解析，提供脱敏样本和预期输出

## 相关链接

- [Python](https://www.python.org/)
- [mitmproxy](https://mitmproxy.org/)
- [Docker](https://www.docker.com/)
- [Git](https://git-scm.com/)
- [GitHub Personal Access Tokens](https://github.com/settings/tokens)
- [微信官网](https://weixin.qq.com/)
- [美团微信小程序说明](./docs/meituan_miniapp.md)
- [数据字段说明](./docs/data.md)
- [常见问题旧文档](./docs/problems.md)

## License

[GPL-3.0](./LICENSE)

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=HUST-hetaisheng/dianping_spider&type=Date)](https://www.star-history.com/#HUST-hetaisheng/dianping_spider&Date)
