# 自动采集 — 操作书

> 总控脚本：`auto_pipeline.py`。前置基础设施（mitm + Clash 分流）已自检 + 自愈，理论上一条命令搞定。

## 一、当前状态（2026-05-22）

| 项目 | 状态 |
|---|---|
| xlsx 门店总数 | **389** |
| 已完成（store_reviews/ 有数据） | 3 (001 逸仙路, 002 华秋路, 059 六道口) |
| 待处理 | **386** |
| 已导出评论 | 1491 条 |
| mitmdump | ✅ 监听 9092（带 `DP_SEARCH_REWRITE=1`） |
| Clash 分流 | ✅ mapi.dianping.com / mapi.meituan.com → DP-MITM |
| events.jsonl | ✅ 已记录 708 条事件 |
| auto_pipeline.py | ✅ 单元测试 10/10 通过 |
| **唯一阻塞** | ❌ PC 微信"大众点评"小程序窗口当前没开 |

代理硬规则：

- GNOME 系统代理必须保持 `127.0.0.1:7890`。
- `mitmdump` 监听 `9092`，不加 `--mode upstream:http://127.0.0.1:7890/`。
- Clash 只把 `mapi.dianping.com`、`mapi.meituan.com`、`mapi.sankuai.com` 分流到 `DP-MITM`。
- 不要把 `m.dianping.com`、`catfront.dianping.com`、`lx0.meituan.com` 分流到 `DP-MITM`，否则容易白屏或影响国内网络。

## 二、回来后的一键启动

```bash
# 1. 在 PC 微信里：打开"大众点评"小程序，进任意一家店的评论页（建议台儿庄店或别的剩余店）
# 2. 然后跑：
cd /media/hetaisheng/thinkplus/dianping_spider
python3 auto_pipeline.py
```

启动后它会自检 + 等窗口出现 + 一家家跑。每跑完 5 家自动导出审计。

## 三、常用调用方式

```bash
# 只跑 5 家试水（推荐先跑 5 家验证完整链路）
python3 auto_pipeline.py --limit 5

# 实验性全自动搜索改写：会额外分流 m.dianping.com，网络更敏感，默认不启用
python3 auto_pipeline.py --limit 1 --include-search-domains

# 单店硬超时设大些（默认 420s = 7 分钟）
python3 auto_pipeline.py --store-timeout 600

# 每 10 家做一次审计（默认 5）
python3 auto_pipeline.py --audit-every 10

# Dry-run 看计划不真跑
python3 auto_pipeline.py --dry-run

# 查看 pipeline 实时日志（另开终端）
tail -f output/auto_pipeline_log.jsonl
tail -f mitm_logs/manual_mitmdump.log
```

## 四、流程链路

```
  ┌─────────────────────────────┐
  │ PC 微信小程序 (大众点评)    │  ← 用户开的，>600x600 的 WeChatAppEx
  │ (xdotool 操作的目标)         │
  └──────────────┬──────────────┘
                 │ 系统代理 = 7890
                 ▼
  ┌─────────────────────────────┐
  │ Clash :7890                 │
  │ DOMAIN-SUFFIX,mapi.dianping.com → DP-MITM
  │ 其他 → 国内/国外节点         │
  └──────┬───────────┬──────────┘
         │ DP-MITM   │
         ▼           ▼ (其他流量)
  ┌──────────────┐  ┌─────────┐
  │ mitmdump     │  │ Clash   │
  │ :9092        │  │ 出口    │
  │ -s dianping_interceptor.py
  │ DP_SEARCH_REWRITE=1
  └──────┬───────┘
         │ 直连点评 API 上游
         ▼
  ┌─────────────────────────────┐
  │ events.jsonl (search/detail/review/city_context)
  │ review_<shopuuid>_*.json     │
  │ search_*.json                │
  └─────────────────────────────┘
```

## 五、auto_pipeline 的自检与自愈

启动后它会：
1. **mitm 自检**：9092 没监听就启动一个新的 mitmdump（带 DP_SEARCH_REWRITE=1）
2. **Clash 自愈**：检测到 `mapi.*` → DP-MITM 规则缺失就调 `manual_review_console.enable_clash_mitm_rule(..., include_search_domains=False)` 重启分流
3. **窗口自检**：等 >600x600 的 WeChatAppEx 出现；窗口消失会重新等
4. **单店超时**：单家店超过 7 分钟就杀子进程，跳下家，**不卡队列**
5. **连续失败保护**：连续 8 家失败暂停（提示人工排查，可能凭证过期）
6. **每 5 家审计**：自动 review_exporter + capture_audit 写出新版本
7. **网络健康检查**：通过 `7890` 探测百度、点评页面和点评静态域名；失败会撤回 DP-MITM 分流并恢复 7890。

## 六、可能出现的问题与对策

| 现象 | 处理 |
|---|---|
| 子进程超时频繁 | 默认 420s 单店超时；评论很多的店调到 600s：`--store-timeout 600` |
| Clash 规则被改回 | auto_pipeline 会自愈；如果失败检查 `output/auto_pipeline_log.jsonl` 里的 `clash_enable_failed` |
| 中文输入失败 | 临时禁用 fcitx：`fcitx -d -r` 或 `setxkbmap us`；mitm 的 search_rewrite 已经能接住大多数情况 |
| 窗口尺寸不是 914x882 | 状态机里 `prepare_window` 会自动 resize；如果坐标偏，跑 `python3 miniapp_state_machine.py --calibrate` 修 miniapp_points.json |
| 连续 8 家失败 | 一般是凭证过期或被风控。手动在小程序滑动几次刷新凭证，或换微信号 |
| 看到 review_capture_failed | 评论 tab 没点中。`miniapp_points.json` 的 `detail_review_count_entry` 调一下 |

## 七、最终交付物

跑完后会有：
- `output/domino_reviews.json` — 所有评论的扁平化 JSON（按 xlsx 门店过滤）
- `output/store_reviews/<NNN>_<name>.json` — 每家店一个 JSON（含元信息）
- `output/capture_audit.json` — 覆盖率报告（含 missing_stores / captured_stores 等）
- `output/auto_pipeline_log.jsonl` — pipeline 自身的运行日志
- `mitm_logs/all_reviews.csv` — 单次抓取的扁平 CSV（含全字段）

通过标准：
```bash
python3 capture_audit.py
# 输出 "缺失门店: 0" 即合格
```
