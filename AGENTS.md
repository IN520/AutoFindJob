# AGENTS.md — 央国企校招追踪表

本文件为 Claude Code / Cursor 等 AI 编码代理提供项目上下文与开发规范。

## 项目概述

聚合国聘网（国资央企平台）与国家大学生就业服务平台（教育部）两个官方源的在招央国企校招岗位，生成可筛选、按截止日期排序的 HTML 追踪报表。

## 快速启动

```bash
python3 tracker.py     # 抓取 + 增量入库 + 导出 jobs.html / jobs.csv / jobs.json
python3 tracker.py --reset   # 清空数据库重新抓
```

无测试套件，通过脚本运行输出与 `jobs.html` 手动验证。

## 项目结构

```
├── SKILL.md              # skill 定义（frontmatter + 使用说明）
├── AGENTS.md             # 本文件
├── tracker.py            # 唯一核心脚本（零依赖，Python 标准库）
├── README.md             # 面向人的说明
├── LICENSE               # MIT
└── .gitignore            # 忽略运行产物 jobs.*
```

## 核心架构

### 数据流

```
crawl_iguopin() → 翻页 fetch_iguopin() 抓推荐池 → 过滤 recruitment_type_cn=="校园招聘"
crawl_ncss()    → 翻页 fetch_ncss() 抓两性质 → 各 ≤100 条
        ↓ normalize_iguopin() / normalize_ncss()  → 统一 schema
        ↓ upsert_rows() → SQLite（job_id 唯一，增量去重，记录 first_seen/last_seen）
        ↓ load_all() → export_csv / export_json / export_html
```

### 关键函数

- `fetch_iguopin(page)`：POST gp-api 推荐池接口，返回单页 list
- `crawl_iguopin()`：翻 20 页，本地过滤校园招聘，按 job_id 去重
- `fetch_ncss(prop, offset)`：GET NCSS 岗位列表接口，按单位性质翻页
- `crawl_ncss()`：抓「国有企业」「机关/事业单位/非营利机构」两个性质
- `normalize_iguopin()/normalize_ncss()`：字段标准化到统一 schema
- `to_k(value, unit)`：国聘薪资（元/月、元/年、元/天）→ K/月
- `extract_city(district_list)`：从国聘 area_cn（"中国-北京-北京市-海淀区"）提取市级
- `upsert_rows()`：增量入库，返回新增数
- `export_html()`：生成自包含 HTML 报表（内联 CSS/JS，客户端筛选排序）

### 数据库

- SQLite，`job_id` 为 PRIMARY KEY
- `DATA_COLS` 常量定义统一 schema 列
- 新记录记 `first_seen`，已存在仅刷新 `last_seen`（支撑增量追踪）

## 两个数据源接口要点

### 国聘网（gp-api.iguopin.com）

```
POST /api/jobs/v1/recom-job
{"search":{"page":1,"page_size":20},"recom":{"update_time":true,"company_nature":true,"hot_job":true}}
```

- 返回 `data.total`（约 400）、`data.list[]`
- 关键字段：`recruitment_type_cn`（社会招聘/校园招聘）、`company_info.nature_cn`（国企/事业单位/国家机关）、`end_time`（截止）、`education_cn`、`min_wage/max_wage`、`wage_unit_cn`、`major_cn`、`district_list[].area_cn`
- 招聘类型编码：校园招聘=`1161T1j6`，社会招聘=`115amZVP`
- 详情页 URL：`https://www.iguopin.com/job/detail?id={job_id}`

### NCSS（ncss.cn）

```
GET /student/jobs/jobslist/ajax/?property=国有企业&offset=1&limit=20&...
```

- 单位性质 `property` 参数为中文（URL 编码）
- 匿名接口最多 100 条（5 页），offset 6 起返回「请登录」
- 关键字段：`jobName`、`recName`、`areaCodeName`、`lowMonthPay/highMonthPay`（K）、`degreeName`、`recProperty`、`recScale`、`recTags`、`major`、`publishDate`（毫秒时间戳）

## 开发规范

1. **零依赖**：只用 Python 标准库，不引入 requests 等第三方包。
2. **请求频率**：每个请求间隔 ≥0.3s，失败退避重试，避免触发限流。
3. **字段变更**：统一 schema 改动需同步改 `DATA_COLS`、`normalize_*`、SQL 建表、导出列、HTML 模板。
4. **HTML 报表**：自包含（内联 CSS/JS），数据通过 `__DATA__` 占位符注入 JSON，客户端做筛选/排序，不依赖后端。
5. **新增数据源**：写 `crawl_xxx()` + `normalize_xxx()`，在 `main()` 里 `upsert_rows` 合并即可。

## 常见陷阱

- NCSS 接口对高频请求会限流（SSL 握手失败/空返回），重试需带退避。
- 国聘 `page_size` 服务端强制上限 20，翻页只能靠 `page` 递增。
- `wage_unit_cn` 可能是「元/年」「元/天」，`to_k()` 需分别换算。
- 国聘 `district_list` 的 `area_cn` 层级不固定（"中国-北京-北京市-海淀区"），`extract_city` 取市级需容错。
