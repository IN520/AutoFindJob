---
name: soe-campus-job-tracker
description: Track and aggregate Chinese state-owned enterprise (央国企/国企/央企) campus recruitment jobs from iguopin.com (国聘网) and ncss.cn (国家大学生就业服务平台). Use when the user wants to find 央国企/国企/央企 campus recruiting positions, build a job tracking table with deadlines, monitor newly posted campus jobs, or get deadline reminders for state-owned enterprise campus hiring.
---

# 央国企校招追踪表 Skill

自动聚合两个官方招聘源，生成一张可筛选、按截止日期排序、临近截止自动高亮的校招追踪表。

## 何时使用

当用户提到以下需求时激活此 skill：

- 找央国企 / 国企 / 央企的校招、应届生、实习岗位
- 建立校招岗位追踪表 / 进度表
- 想知道哪些央国企正在校招、哪些快截止了
- 每日监控新发布的央国企校招岗位

## 前置条件

- Python 3（仅标准库，无第三方依赖）
- 网络可访问 iguopin.com 与 ncss.cn

## 快速开始

```bash
python3 tracker.py          # 抓取 + 增量入库 + 导出
open jobs.html              # 查看可筛选报表
```

建议每天跑一次，或配合 cron / 定时任务自动运行。

## 它能做什么

| 功能 | 说明 |
|---|---|
| 🔍 双源聚合 | 国聘网（国资央企平台）+ 国家大学生就业服务平台（教育部） |
| 📅 截止时间 | 国聘网源含 `end_time`，报表默认按截止日期升序，临近自动标红 |
| 🏢 公司性质 | 国企 / 央企 / 事业单位 / 国家机关，可直接筛选 |
| 🔎 多维筛选 | 关键词、城市、学历、公司性质、来源 |
| 📤 多格式导出 | HTML 报表（核心）、CSV、JSON、SQLite |
| 🔁 增量去重 | `job_id` 唯一，重复运行不重复计数 |

## 运行机制（重要）

### 数据源 1：国聘网

- 接口：`POST https://gp-api.iguopin.com/api/jobs/v1/recom-job`
- 请求体：`{"search":{"page":N,"page_size":20},"recom":{"update_time":true,"company_nature":true,"hot_job":true}}`
- 翻页抓取推荐池（约 400 条），本地过滤 `recruitment_type_cn == "校园招聘"`
- 字段：`company_info.nature_cn`（公司性质）、`end_time`（截止时间）、`education_cn`（学历）、`min_wage/max_wage`（薪资，元/月→K）、`major_cn`（专业）、`district_list`（工作地）

### 数据源 2：国家大学生就业服务平台

- 接口：`GET https://www.ncss.cn/student/jobs/jobslist/ajax/`
- 参数：`property=国有企业` / `property=机关/事业单位/非营利机构`
- 限制：匿名接口每个查询最多返回 100 条（5 页），超出提示「请登录」

### 统一 Schema

`source, job_id, title, company, city, degree, salary_low, salary_high, property, scale, headcount, welfare, major, publish_date, deadline, url`

## 产出文件

| 文件 | 说明 |
|---|---|
| `jobs.html` | 核心交付物：可搜索/筛选/排序的网页报表，临近截止标红 |
| `jobs.csv` | 全量数据，Excel 直接打开 |
| `jobs.db` | SQLite 增量存储 |
| `jobs.json` | 标准化 JSON |

> 这些均为运行产物，已加入 `.gitignore`，不进入版本库。

## 已知限制（务必如实告知用户）

1. 国聘网匿名接口仅能拿到约 400 条「推荐池」，其搜索接口 `/api/jobs/v3/list` 需要登录态/签名，暂未接入 → 会漏掉推荐池之外的岗位。
2. NCSS 匿名接口有 100 条/筛选上限，且无截止时间字段。
3. 因此本表是「在招央国企校招岗的高质量子集」，不是严格全量。

## 合规

- 仅抓取公开可访问的招聘信息，控制请求频率（每个请求间隔 ≥0.3s）。
- 本 skill 只聚合公开信息，不自动投递、不绕过登录或验证码。
