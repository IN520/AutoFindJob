#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
央国企校招追踪表
数据源（双源）：
  1. 国聘网 (iguopin.com) —— 国资央企招聘平台，含截止时间、公司性质、校招/社招标记
  2. 国家大学生就业服务平台 (ncss.cn) —— 教育部官方平台，单位性质=国有企业/机关·事业单位

零第三方依赖，仅用 Python 标准库。每天重跑一次即可看到最新在招岗位。

用法：
    python3 tracker.py

产出（同目录下）：
    jobs.db     SQLite，job_id 唯一，支撑增量去重
    jobs.csv    在招岗位（Excel 可直接打开）
    jobs.html   可筛选/排序/临近截止高亮的网页报表（核心交付物）
    jobs.json   原始标准化数据
"""

import os
import json
import csv
import time
import sqlite3
import argparse
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "jobs.db")
CSV_PATH = os.path.join(BASE_DIR, "jobs.csv")
JSON_PATH = os.path.join(BASE_DIR, "jobs.json")
HTML_PATH = os.path.join(BASE_DIR, "jobs.html")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36")

TZ_CN = timezone(timedelta(hours=8))

NCSS_PROPERTIES = ["国有企业", "机关/事业单位/非营利机构"]
NCSS_API = "https://www.ncss.cn/student/jobs/jobslist/ajax/"

IGUOPIN_API = "https://gp-api.iguopin.com/api/jobs/v1/recom-job"
IGUOPIN_RECOM = {"update_time": True, "company_nature": True, "hot_job": True}


# ---------- 抓取：国家大学生就业服务平台 ----------

def fetch_ncss(prop, offset, retries=3):
    qs = {
        "jobType": "", "areaCode": "", "jobName": "", "monthPay": "",
        "industrySectors": "", "property": prop, "categoryCode": "",
        "memberLevel": "", "recruitType": "", "offset": offset,
        "limit": 20, "keyUnits": "", "degreeCode": "",
        "sourcesName": "0", "sourcesType": "",
    }
    url = NCSS_API + "?" + urllib.parse.urlencode(qs)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.load(r)
            if data.get("flag") and data.get("data"):
                return data["data"].get("list") or []
            return []
        except Exception as e:
            if attempt == retries - 1:
                print(f"    [!] NCSS offset={offset} 失败: {e}")
                return []
            time.sleep(2.0 * (attempt + 1))
    return []


def crawl_ncss():
    jobs = {}
    for prop in NCSS_PROPERTIES:
        empty_streak = 0
        for page in range(1, 7):
            items = fetch_ncss(prop, page)
            if not items:
                empty_streak += 1
                if empty_streak >= 2:
                    break
                continue
            empty_streak = 0
            for it in items:
                if it.get("jobId"):
                    jobs[it["jobId"]] = it
            if len(items) < 20:
                break
            time.sleep(0.35)
    return jobs


# ---------- 抓取：国聘网 ----------

def fetch_iguopin(page, retries=3):
    body = json.dumps({"search": {"page": page, "page_size": 20},
                       "recom": IGUOPIN_RECOM})
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                IGUOPIN_API, data=body.encode(),
                headers={"User-Agent": UA, "Content-Type": "application/json",
                         "Referer": "https://www.iguopin.com/job/list"},
                method="POST")
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.load(r)
            return (data.get("data") or {}).get("list") or []
        except Exception as e:
            if attempt == retries - 1:
                print(f"    [!] 国聘 page={page} 失败: {e}")
                return []
            time.sleep(2.0 * (attempt + 1))
    return []


def crawl_iguopin():
    jobs = {}
    for page in range(1, 21):  # 推荐池上限约 400 条
        lst = fetch_iguopin(page)
        if not lst:
            break
        for it in lst:
            # 只保留校园招聘/校招/实习
            if it.get("recruitment_type_cn") == "校园招聘" and it.get("job_id"):
                jobs[it["job_id"]] = it
        if len(lst) < 20:
            break
        time.sleep(0.3)
    return jobs


# ---------- 字段标准化 ----------

def ms_to_date(ms):
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=TZ_CN).strftime("%Y-%m-%d")
    except Exception:
        return ""


def to_k(value, unit):
    """把国聘薪资换算成 K/月。"""
    if value is None:
        return None
    try:
        v = float(value)
    except Exception:
        return None
    u = unit or ""
    if "年" in u:
        return round(v / 12000, 1)
    if "天" in u or "日" in u:
        return round(v / 1000, 1)  # 按日薪保留 K
    return round(v / 1000, 1)  # 元/月 → K/月


def extract_city(district_list):
    if not district_list:
        return ""
    area = district_list[0].get("area_cn") or ""
    parts = [p for p in area.split("-") if p and p != "中国"]
    if len(parts) >= 3:
        return parts[-2]  # 取市级
    return parts[-1] if parts else ""


def normalize_ncss(item):
    low = item.get("lowMonthPay")
    high = item.get("highMonthPay")
    return {
        "source": "国家大学生就业服务平台",
        "job_id": item.get("jobId", ""),
        "title": (item.get("jobName") or "").strip(),
        "company": (item.get("recName") or "").strip(),
        "city": (item.get("areaCodeName") or "").strip(),
        "degree": (item.get("degreeName") or "").strip(),
        "salary_low": int(float(low)) if low is not None else None,
        "salary_high": int(float(high)) if high is not None else None,
        "property": (item.get("recProperty") or "").strip(),
        "scale": (item.get("recScale") or "").strip(),
        "headcount": item.get("headCount"),
        "welfare": (item.get("recTags") or "").strip(),
        "major": (item.get("major") or "").strip(),
        "publish_date": ms_to_date(item.get("publishDate")),
        "deadline": "",
        "url": f"https://www.ncss.cn/student/jobs/{item.get('jobId')}/detail.html",
    }


def normalize_iguopin(item):
    ci = item.get("company_info") or {}
    unit = item.get("wage_unit_cn") or ""
    tags = "、".join(item.get("job_custom_tags_cn") or [])
    majors = "、".join(item.get("major_cn") or [])
    return {
        "source": "国聘网",
        "job_id": item.get("job_id", ""),
        "title": (item.get("job_name") or "").strip(),
        "company": (item.get("company_name") or "").strip(),
        "city": extract_city(item.get("district_list")),
        "degree": (item.get("education_cn") or "").strip(),
        "salary_low": to_k(item.get("min_wage"), unit),
        "salary_high": to_k(item.get("max_wage"), unit),
        "property": (ci.get("nature_cn") or "").strip(),
        "scale": (ci.get("scale_cn") or "").strip(),
        "headcount": item.get("amount"),
        "welfare": tags,
        "major": majors,
        "publish_date": (item.get("start_time") or "")[:10],
        "deadline": (item.get("end_time") or "")[:10],
        "url": f"https://www.iguopin.com/job/detail?id={item.get('job_id')}",
    }


# ---------- 存储 ----------

DATA_COLS = ["source", "title", "company", "city", "degree",
             "salary_low", "salary_high", "property", "scale",
             "headcount", "welfare", "major", "publish_date",
             "deadline", "url"]


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            source TEXT, title TEXT, company TEXT, city TEXT, degree TEXT,
            salary_low REAL, salary_high REAL, property TEXT,
            scale TEXT, headcount INTEGER, welfare TEXT, major TEXT,
            publish_date TEXT, deadline TEXT, url TEXT,
            first_seen TEXT, last_seen TEXT
        )
    """)
    conn.commit()
    return conn


def upsert_rows(conn, norm_rows):
    now = datetime.now(TZ_CN).strftime("%Y-%m-%d %H:%M:%S")
    new_count = 0
    for r in norm_rows:
        if not r["job_id"]:
            continue
        exists = conn.execute(
            "SELECT 1 FROM jobs WHERE job_id=?", (r["job_id"],)).fetchone()
        if exists:
            conn.execute(
                f"UPDATE jobs SET {', '.join(c + '=?' for c in DATA_COLS)}, "
                f"last_seen=? WHERE job_id=?",
                [r[c] for c in DATA_COLS] + [now, r["job_id"]])
        else:
            new_count += 1
            conn.execute(
                f"INSERT INTO jobs (job_id, first_seen, last_seen, "
                f"{', '.join(DATA_COLS)}) VALUES (?, ?, ?, "
                f"{', '.join('?' for _ in DATA_COLS)})",
                [r["job_id"], now, now] + [r[c] for c in DATA_COLS])
    conn.commit()
    return new_count


def load_all(conn):
    cur = conn.execute("SELECT * FROM jobs ORDER BY "
                       "CASE WHEN deadline='' THEN 1 ELSE 0 END, "
                       "deadline ASC, company")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------- 导出 ----------

def export_csv(rows):
    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["公司", "岗位", "城市", "学历", "月薪下限(K)", "月薪上限(K)",
                    "公司性质", "规模", "招聘人数", "福利", "专业要求",
                    "发布日期", "截止日期", "投递链接", "来源"])
        for r in rows:
            w.writerow([
                r["company"], r["title"], r["city"], r["degree"],
                r["salary_low"] or "", r["salary_high"] or "",
                r["property"], r["scale"], r["headcount"] or "",
                r["welfare"], r["major"], r["publish_date"], r["deadline"],
                r["url"], r["source"],
            ])
    print(f"  ✓ CSV 已导出: {CSV_PATH} ({len(rows)} 行)")


def export_json(rows):
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"  ✓ JSON 已导出: {JSON_PATH}")


def export_html(rows, generated_at):
    rows_json = json.dumps(rows, ensure_ascii=False)
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>央国企校招追踪表</title>
<style>
:root{--bg:#f5f6f8;--card:#fff;--line:#e6e8ec;--txt:#1a1d24;--mut:#8a93a3;--brand:#c8102e;}
*{box-sizing:border-box}body{margin:0;font:14px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--txt)}
header{background:linear-gradient(135deg,#8b1223,#c8102e);color:#fff;padding:22px 26px}
header h1{margin:0 0 4px;font-size:20px}header p{margin:0;opacity:.85;font-size:13px}
.wrap{max-width:1220px;margin:18px auto;padding:0 14px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card .n{font-size:24px;font-weight:700}.card .l{color:var(--mut);font-size:12px}
.toolbar{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:14px}
.toolbar input,.toolbar select{padding:8px 10px;border:1px solid var(--line);border-radius:8px;font-size:13px}
.toolbar input{flex:1;min-width:220px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:9px 10px;text-align:left;border-bottom:1px solid var(--line);font-size:13px;vertical-align:top}
th{background:#fafbfc;cursor:pointer;user-select:none;white-space:nowrap;color:#3a3f4a}
th:hover{background:#f1f3f6}
tbody tr:hover{background:#fafafc}
td a{color:#c8102e;text-decoration:none}
.tag{display:inline-block;padding:1px 7px;border-radius:20px;font-size:11px;background:#fdeef0;color:#c8102e}
.tag.gov{background:#eef3fd;color:#2b5fd9}
.mut{color:var(--mut)}
.welfare{max-width:240px;color:#5a6170;font-size:12px}
.deadline{font-weight:600}
.deadline.urgent{color:#c8102e}
.deadline.soon{color:#e07b00}
footer{max-width:1220px;margin:16px auto 40px;padding:0 14px;color:var(--mut);font-size:12px}
</style>
</head>
<body>
<header>
  <h1>央国企校招追踪表</h1>
  <p>数据源：国聘网（国资央企平台）+ 国家大学生就业服务平台 · 生成时间 __GEN__ · 建议每日重跑更新</p>
</header>
<div class="wrap">
  <div class="cards">
    <div class="card"><div class="n" id="cTotal">0</div><div class="l">在招校招岗位</div></div>
    <div class="card"><div class="n" id="cCompany">0</div><div class="l">招聘单位</div></div>
    <div class="card"><div class="n" id="cCity">0</div><div class="l">覆盖城市</div></div>
    <div class="card"><div class="n" id="cUrgent">0</div><div class="l">7天内截止</div></div>
  </div>
  <div class="toolbar">
    <input id="q" placeholder="搜索：公司 / 岗位 / 专业 / 福利关键词…">
    <select id="fCity"><option value="">全部城市</option></select>
    <select id="fDegree"><option value="">全部学历</option></select>
    <select id="fProp"><option value="">全部性质</option></select>
    <select id="fSrc"><option value="">全部来源</option></select>
  </div>
  <table id="tbl">
    <thead><tr>
      <th data-k="company">公司</th><th data-k="title">岗位</th>
      <th data-k="city">城市</th><th data-k="degree">学历</th>
      <th data-k="salary_low">月薪</th><th data-k="property">性质</th>
      <th data-k="deadline">截止日期</th><th data-k="welfare">福利/专业</th>
    </tr></thead>
    <tbody></tbody>
  </table>
</div>
<footer>本表仅聚合公开在招信息，投递前请到官网核对岗位详情与截止时间；红色=7天内截止，橙色=30天内截止。</footer>
<script>
const DATA = __DATA__;
const $ = s => document.querySelector(s);
function uniq(a){return [...new Set(a)]}
const cities = uniq(DATA.map(r=>r.city).filter(Boolean)).sort();
const degrees = uniq(DATA.map(r=>r.degree).filter(Boolean)).sort();
const props = uniq(DATA.map(r=>r.property).filter(Boolean)).sort();
const srcs = uniq(DATA.map(r=>r.source).filter(Boolean)).sort();
function fillSelect(sel, arr){arr.forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;sel.appendChild(o)})}
fillSelect($('#fCity'),cities);fillSelect($('#fDegree'),degrees);fillSelect($('#fProp'),props);fillSelect($('#fSrc'),srcs);
let sortKey='deadline', sortDir=1;
const today = new Date(); today.setHours(0,0,0,0);
function daysLeft(d){if(!d)return null;const t=new Date(d+'T23:59:59');return Math.ceil((t-today)/86400000);}
function render(){
  const q=$('#q').value.trim().toLowerCase();
  const fc=$('#fCity').value, fd=$('#fDegree').value, fp=$('#fProp').value, fs=$('#fSrc').value;
  let rows=DATA.filter(r=>{
    if(fc&&r.city!==fc)return false;
    if(fd&&r.degree!==fd)return false;
    if(fp&&r.property!==fp)return false;
    if(fs&&r.source!==fs)return false;
    if(q){const hay=(r.company+r.title+r.city+r.welfare+r.major+r.property+r.source).toLowerCase();if(!hay.includes(q))return false;}
    return true;
  });
  rows.sort((a,b)=>{
    let x=a[sortKey],y=b[sortKey];
    if(sortKey==='deadline'){const da=daysLeft(x),db=daysLeft(y);
      if(da===null&&db===null)return 0;if(da===null)return 1;if(db===null)return -1;return (da-db)*sortDir;}
    if(typeof x==='number'&&typeof y==='number')return (x-y)*sortDir;
    x=String(x??'');y=String(y??'');
    return x.localeCompare(y,'zh')*sortDir;
  });
  const tb=$('#tbl tbody');tb.innerHTML='';
  rows.forEach(r=>{
    const sal=(r.salary_low!=null&&r.salary_high!=null)?(r.salary_low+'–'+r.salary_high+'K'):'面议';
    const propCls=(/国企|央企|事业单位|机关/.test(r.property))?'gov':'';
    const dl=daysLeft(r.deadline);
    let dlCls='', dlTxt=r.deadline||'—';
    if(dl!==null){ if(dl<=7)dlCls='urgent'; else if(dl<=30)dlCls='soon'; if(dl<0)dlTxt=r.deadline+' (已截止)'; }
    const tr=document.createElement('tr');
    tr.innerHTML='<td><a href="'+r.url+'" target="_blank" rel="noopener">'+r.company+'</a></td>'
      +'<td>'+r.title+'</td><td>'+r.city+'</td><td>'+r.degree+'</td>'
      +'<td>'+sal+'</td><td><span class="tag '+propCls+'">'+(r.property||r.source)+'</span></td>'
      +'<td class="deadline '+dlCls+'">'+dlTxt+'</td>'
      +'<td class="welfare">'+[r.welfare,r.major].filter(Boolean).join(' · ')+'</td>';
    tb.appendChild(tr);
  });
  $('#cTotal').textContent=rows.length;
  $('#cCompany').textContent=uniq(rows.map(r=>r.company)).length;
  $('#cCity').textContent=uniq(rows.map(r=>r.city).filter(Boolean)).length;
  $('#cUrgent').textContent=rows.filter(r=>{const d=daysLeft(r.deadline);return d!==null&&d<=7&&d>=0;}).length;
}
document.querySelectorAll('th').forEach(th=>th.addEventListener('click',()=>{
  const k=th.dataset.k;
  if(sortKey===k)sortDir*=-1;else{sortKey=k;sortDir=1;}
  render();
}));
$('#q').addEventListener('input',render);
$('#fCity').addEventListener('change',render);
$('#fDegree').addEventListener('change',render);
$('#fProp').addEventListener('change',render);
$('#fSrc').addEventListener('change',render);
render();
</script>
</body>
</html>"""
    html = html.replace("__GEN__", generated_at).replace("__DATA__", rows_json)
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✓ HTML 报表已导出: {HTML_PATH}")


# ---------- 主流程 ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="清空数据库重新抓取")
    args = ap.parse_args()

    if args.reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    print("=" * 60)
    print("央国企校招追踪表 · 国聘网 + 国家大学生就业服务平台")
    print("=" * 60)

    conn = init_db()

    print("\n▶ 抓取国聘网（校园招聘，含截止时间）...")
    ig_jobs = crawl_iguopin()
    ig_rows = [normalize_iguopin(it) for it in ig_jobs.values()]
    print(f"  · 国聘网校园招聘：{len(ig_rows)} 条")

    print("\n▶ 抓取国家大学生就业服务平台（国有企业/机关·事业单位）...")
    nc_jobs = crawl_ncss()
    nc_rows = [normalize_ncss(it) for it in nc_jobs.values()]
    print(f"  · 国家平台：{len(nc_rows)} 条")

    new = upsert_rows(conn, ig_rows + nc_rows)
    all_rows = load_all(conn)
    conn.close()

    print(f"\n▶ 库中共 {len(all_rows)} 个在招岗位（本次新增 {new}）")
    generated_at = datetime.now(TZ_CN).strftime("%Y-%m-%d %H:%M")
    export_csv(all_rows)
    export_json(all_rows)
    export_html(all_rows, generated_at)
    print("\n完成。用浏览器打开 jobs.html 查看可筛选报表。")


if __name__ == "__main__":
    main()
