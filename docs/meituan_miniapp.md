# 美团微信小程序 API 抓取

这套增量支持不改现有大众点评链路，单独走美团入口，日志和导出文件全部隔离：

- 抓包日志：`mitm_logs/meituan/`
- 总导出：`output/meituan_reviews.json`
- 每店导出：`output/meituan_store_reviews/`

## 1. 启动 mitm 拦截

```bash
mitmdump --listen-port 9092 --set ssl_insecure=true \
  -s /home/hetaisheng/dianping_spider/meituan_miniapp_interceptor.py
```

这个入口复用了现有小程序 API 解析逻辑，但会把美团抓包单独写到 `mitm_logs/meituan/`，不会和大众点评混在一起。
默认只接收独立美团微信小程序 appid `wxde8ac0a21135c07d` 的流量，不会把大众点评宿主 `wx734c1ad7b3562129` 混进来。

## 2. 在 PC 微信里操作美团小程序

手动打开美团微信小程序，完成下面动作：

1. 搜索门店
2. 进入门店页
3. 打开评论页
4. 下拉翻页，让评论 API 多返回几页

当前已确认/接入的核心接口分两类：

- 独立美团小程序通用宿主流量：按 `csecappid=wxde8ac0a21135c07d` 过滤
- 从本机独立美团小程序日志确认过的真实搜索相关接口：
  - `https://apimobile.meituan.com/group/v1/deal/searchpage/hotword/city/divide/hotrecommend/<cityId>`
  - `https://apimobile.meituan.com/group/v1/deal/search/suggest/<cityId>`
  - `https://apimobile.meituan.com/group/v4/poi/search/miniprogram/<cityId>`
- 已验证可解析的点评宿主外卖样本：
  - 搜索：`minitakeoutsearch.bin`
  - 评论：`shopreview`

主键目前支持：

- `shopId`
- `shopUuid`
- `poi_id_str` / `poiIdStr`
- `wmPoiId` / `mtwmpoiid`

如果 `shopName` 带有 `代购`，导出时会自动归一化，不影响和 Excel 门店名对齐。

## 3. 解析门店 ID

```bash
python3 meituan_shop_id_resolver.py
```

如果默认文件名不存在，也可以显式指定：

```bash
python3 meituan_shop_id_resolver.py --excel 门店抽样.xlsx
```

输出：

- `output/meituan/meituan_shop_id_map.json`
- `output/meituan/meituan_needs_manual_match.json`

## 4. 导出评论

```bash
python3 meituan_review_exporter.py
```

如果默认文件名不存在，也可以显式指定：

```bash
python3 meituan_review_exporter.py --excel 门店抽样.xlsx
```

输出：

- `output/meituan_reviews.json`
- `output/meituan_store_reviews/*.json`

## 5. 现有能力边界

这次增量已经支持：

- 独立的美团小程序抓包入口
- 独立美团 appid 过滤：`wxde8ac0a21135c07d`
- 独立的美团日志目录
- 已确认独立美团小程序至少会访问 `apimobile.meituan.com/group/v4/poi/search/miniprogram/<cityId>` 这类搜索接口
- 已从独立美团源码和运行日志定位到评论相关 endpoint 前缀：
  - `https://web.meituan.com/web/poi/`
  - `https://web.meituan.com/web/comment/`
  - `https://i.meituan.com/brunch/applet/review`
- 美团搜索结果里的 `shopId` / `takeoutShopList`
- `poi_id_str / poiIdStr / wmPoiId / mtwmpoiid` 主键兜底
- `shopName` 中带分店名、带 `代购` 的门店归一化匹配
- 美团 `shopreview` 评论导出

还没有完成的部分：

- 还没拿到独立美团小程序 `wxde8ac0a21135c07d` 的真实评论接口成功样本做端到端验证
- 还没有单独新增“美团小程序 UI 自动点击状态机”

如果你要把大众点评那套自动搜店/自动滚动也复制成美团版，下一步直接在这套独立入口上补一个 `run_one_meituan_shop.py` 即可。
