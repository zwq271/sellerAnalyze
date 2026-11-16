选品视频库 — 免费浏览器采集版

启动
  双击 start.command，或在本目录运行 .venv/bin/python app.py
  打开 http://127.0.0.1:8765
  停止：在运行服务的终端按 Ctrl+C。服务只监听本机 127.0.0.1。
  已安装 Python 环境、yt-dlp 和 Playwright，优先使用本机 Google Chrome。
  其他电脑需要 Python 3.10+；没有 Chrome 时脚本尝试安装 Chromium。

免费采集
  1. 选择目标市场（默认美国）和带货类目。
  2. 输入英文商品词，点击“采集 TikTok”；未填词时使用所选类目的英文检索词。
  3. 程序打开独立浏览器，读取搜索页实际返回的视频数据，一次最多 50 条。
  4. 如提示登录或验证，点击“登录 TikTok”，在弹出的窗口手动完成。
  5. 回到工作台点击“完成登录”，再重新点击采集。
  6. 采集结果保存到本地视频库，可按条件筛选、查看商品、下载或导出。
  搜索会给商品词补充 tiktok shop 以提高带货内容相关性，但不保证检索完整性。

数据口径
  - 目标市场不是已确认的销售市场。免费搜索会受网络、会话和个性化影响。
  - 无法确认市场时 country=UNKNOWN、target_market=US；美国筛选也会包含这些明确标注的候选视频。
  - 类目按视频文案关键词推断，保存 category_evidence，不当作 TikTok 官方类目。
  - TikTok 明确 isECVideo=1 或响应包含商品 ID 时才标为带货。
  - 文案 #tiktokshop、#ad 等仅作为线索，不单独确认带货，is_commerce 保持 null。
  - 默认展示待核验候选视频；打开“只看明确标记的带货视频”可排除未知状态。
  - 商品只保留响应中的明确 ID、名称和链接。价格单位不明确时不猜测。
  - 销量与销售额缺失留空，不从播放量推算订单。
  - 互动率仅在播放、赞、评论、分享都可用时计算：(赞+评论+分享)/播放量×100%。
  - 免费刷新保留旧记录中已有商品和销售指标，并保存 field_sources 字段来源。
  - 不同币种不直接进行销售额筛选与排序。

筛选、下载和导出
  支持目标市场、类目、文案或商品关键词、发布日期、播放量、预估销量/销售额筛选。
  多件关联商品可在“查看详情”查看；支持 JSON / CSV 导出。
  下载使用 yt-dlp，可尝试复用独立浏览器的 TikTok 会话。
  成功下载保存到 downloads/<任务ID>/video.*，同目录 metadata.json 包含关联商品数据。
  平台可能不提供带货视频媒体地址；下载失败会显示原因，可重试，不承诺所有视频可下载。

本地文件
  data/library.sqlite3：视频库和下载任务。
  data/tiktok-browser/：独立浏览器会话，不读取你平时浏览器的个人配置。
  data/tiktok-cookies.txt：供下载复用的会话文件，仅保存在本机，文件权限为 600。
  data/、downloads/、.venv/ 均在 .gitignore 中，请勿分享登录会话文件。

数据导入
  支持 UTF-8 CSV 或 JSON 数组，每次最多 5000 条 / 10MB，逐行验证后整批保存。
  source 必填。video_id 和 products[].id 用字符串，避免 19 位 ID 精度损失。
  published_at 使用带时区 ISO 时间，如 2026-11-12T20:56:10-08:00。
  is_commerce 为 true / false / null；缺失不自动确认带货。
  engagement_rate / ad_view_ratio 单位是百分数：0.51 表示 0.51%。
  metrics_period 写明外部销售指标的统计周期。
  products 是对象数组，支持 id,name,url,image,price,currency,shop,source,evidence。
  CSV 中 products 可使用双引号转义后的 JSON 字符串，也可使用扁平字段：
  product_id,product_name,product_url,product_image,product_price,product_currency,product_shop。
  相同视频 ID 的手工导入会更新完整记录；免费采集刷新则保留已有的非空历史字段。

验证
  .venv/bin/python -m unittest discover -s tests -v
  .venv/bin/python scripts/check_ui.py
  后者使用临时数据库检查桌面/手机布局、导入、商品详情、带货过滤和 CSV 导出，不污染用户数据。
  首次真实未登录搜索未获取视频结果；仍需完成手动登录后测量采集和带货视频下载成功率。

实现依据
  Playwright 官方：https://playwright.dev/python/docs/network
  开源采集工程调研：https://github.com/Evil0ctal/Douyin_TikTok_Download_API
  当前免费采集模块为本地实现，不依赖该项目的付费赞助商接口。
