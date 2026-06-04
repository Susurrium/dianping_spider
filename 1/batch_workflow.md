# 批量采集达美乐门店评论 - 操作指南

目标只导出 `达美乐_门店爬虫.xlsx` 内的门店评论，最终文件：

```bash
output/domino_reviews.json
```

字段：

```json
{"门店": "达美乐比萨(逸仙路店)", "发布时间": "...", "发布人": "...", "文字": "..."}
```

## 当前架构

不要再使用 `auto_xdotool_scraper.py` 作为主入口；它是早期实验脚本，误用了桌面/浏览器 `Ctrl+F`，不能代表小程序内搜索。

现在有两条链路：

### A. 稳定链路：UI 触发，mitm 判定

1. `dianping_interceptor.py`
   - mitmproxy 拦截真实 PC 微信小程序请求。
   - 保存搜索/评论原始响应。
   - 追加结构化事件到 `mitm_logs/events.jsonl`。
2. `miniapp_state_machine.py`
   - 用 xdotool 只负责触发小程序 UI 动作。
   - 每一步是否成功只看 `events.jsonl`：
     - 城市：`city_context/search/takeout_search` 且 cityId 正确。
     - 搜索：`search/takeout_search` 且 keyword/cityId 正确。
     - 详情：`unifyshopaggregatedump.bin` 且 shopuuid 正确。
     - 评论：`outsideshopreviewlist/shopreview` 且 shopuuid 正确。
3. `review_exporter.py`
   - 只导出 xlsx 内门店。
   - 输出分析用 JSON。

这条链路仍然需要少量 UI 点击，但成功/失败不靠坐标猜测，而靠真实 API 事件确认。

### B. 诊断链路：mitm 队列改包，不作为主采集路线

PC 微信小程序目前没有暴露可用的 DevTools/CDP 控制端口，不能像 Playwright 操作网页 DOM 那样直接点内部节点。已确认大众点评包在：

```text
~/.xwechat/radium/Applet/packages/wx734c1ad7b3562129/693/
```

可解包/strings 分析页面和接口，但这不等于能直接调用小程序内部函数。已经从真实包确认评论接口是：

```text
https://mapi.dianping.com/mapi/review/outsidesiftedreviewlist.bin
```

关键参数是 `referid=<shopUuid>`、`start=<分页起点>`、`filterid=800`，响应结构是 `data.list`、`data.shopUuid`、`data.shopName`、`data.nextStartIndex`、`data.isEnd`。

注意：该请求带 `mtgsig` 和风控上下文。实测把 live request 的 `referid/start` 改成队列目标后返回过 `403`，说明签名/风控上下文大概率和原始门店及分页绑定。因此 `mitm_queue_interceptor.py` 只能作为诊断工具，不能作为稳定批量主线。

先生成队列：

```bash
python3 auto_shop_uuid_resolver.py
python3 review_queue_builder.py --limit 1
```

启动队列拦截器：

```bash
python3 mitm_manager.py --queue --replace
```

然后在 PC 微信大众点评小程序中进入任意一家店的评论页，滚动。脚本会尝试把这些真实评论请求重写到队列中的目标店铺，结果写入：

```text
mitm_logs/review_queue.json
mitm_logs/review_queue_progress.json
mitm_logs/queue_reviews/
```

如果返回 403、空结果或目标店铺不变，结论就是这条链路不可用，回到 A 链路。

如果看到 `Address already in use`，说明已有 mitmweb 占着代理或 Web 端口。先查状态：

```bash
python3 mitm_manager.py --status
```

需要替换成队列版时使用：

```bash
python3 mitm_manager.py --queue --replace
```

## 代理必须先正确

当前稳定链路是：

```text
PC 微信小程序 -> 系统代理 127.0.0.1:7890 -> Clash
Clash 仅将 mapi.dianping.com / mapi.meituan.com / mapi.sankuai.com 分流到 127.0.0.1:9092
其他国内/国外流量仍由 Clash 正常处理
```

不要把 GNOME 系统代理切到 `9092`。`9092` 只给 Clash 的 `DP-MITM` 规则转发点评 API 用。

手动恢复/确认系统代理：

```bash
gsettings get org.gnome.system.proxy.http port
gsettings get org.gnome.system.proxy.https port
gsettings set org.gnome.system.proxy.http host 127.0.0.1
gsettings set org.gnome.system.proxy.http port 7890
gsettings set org.gnome.system.proxy.https host 127.0.0.1
gsettings set org.gnome.system.proxy.https port 7890
```

手工启动稳定的命令行版 mitm，不要加 upstream：

```bash
mitmdump --listen-port 9092 --set ssl_insecure=true \
  -s /media/hetaisheng/thinkplus/dianping_spider/dianping_interceptor.py
```

然后启用 Clash API 分流：

```bash
python3 - <<'PY'
from manual_review_console import enable_clash_mitm_rule
enable_clash_mitm_rule(proxy_port=9092, include_search_domains=False)
PY
```

首次安装 mitmproxy 证书时打开：

```text
http://mitm.it
```

如果网络异常，先撤回 DP-MITM 分流并恢复 7890：

```bash
python3 - <<'PY'
from manual_review_console import disable_clash_mitm_rule, restore_clash_proxy
disable_clash_mitm_rule()
restore_clash_proxy()
PY
```

## 坐标校准

生成默认点位：

```bash
python3 miniapp_state_machine.py --calibrate
```

编辑 `miniapp_points.json`，所有点位都是小程序窗口内相对坐标：

- `city_button`：小程序左上城市按钮。
- `city_search_input`：城市选择页搜索框。
- `city_first_result`：城市搜索结果第一项。
- `search_input`：小程序真实搜索框，不能是浏览器/微信外层查找框。
- `first_shop_result`：搜索结果第一条店铺的可点击区域。
- `result_row_height`：搜索结果每条之间的高度，用于点击第 N 条候选。
- `review_tab`：详情页“评价/评论”入口。

## 试跑

先离线看计划：

```bash
python3 miniapp_state_machine.py --dry-run --limit 2
```

真实采集指定 xlsx 原始序号的一家，例如 #002 华秋路店：

```bash
python3 miniapp_state_machine.py --start-mitm --proxy-mode clash-rule --original-index 2 --min-reviews 10
```

真实采集下一家未完成门店：

```bash
python3 miniapp_state_machine.py --start-mitm --proxy-mode clash-rule --limit 1 --min-reviews 10
```

确认 `mitm_logs/events.jsonl` 中出现目标店铺的 `review` 事件后，再扩大批量：

```bash
python3 miniapp_state_machine.py --start-mitm --proxy-mode clash-rule --limit 20
```

采集后立即审计覆盖率：

```bash
python3 capture_audit.py
```

它会输出 xlsx 门店数、已导出门店、缺失门店、评论数，并写入：

```text
output/capture_audit.json
```

## 城市问题

xlsx 有多城市门店。状态机会从地址解析城市。首家或城市未知时，状态机会先搜索，并用真实搜索事件里的 `cityId` 确认城市；只有搜索事件城市不匹配时才切换城市。这样可以避免当前页面已经是上海时，误点左上城市按钮打开右侧“选择地址”页，导致搜索落在旧首页词或旧商户上。

如果某城市切换失败，优先检查：

1. `miniapp_points.json` 的城市按钮/城市搜索框坐标。
2. mitm 是否抓到 `city_context` 或 `search` 事件。
3. `docs/location.md` 中是否有该城市的 cityId。

## 导出

任何时候都可以重新导出：

```bash
python3 review_exporter.py --output output/domino_reviews.json
```
