# Legal Website Crawler

法律网站爬虫模块，用于采集法律名称、条文内容、适用场景、相关案例等法律数据。

## 功能特性

- ✅ **多数据源支持**：华律网（66law.cn，主）+ 找法网（findlaw.cn，备）
- ✅ **robots.txt 合规**：自动检查并遵守网站的 robots.txt 规则
- ✅ **反爬策略**：随机 User-Agent、请求延时（3-5秒）
- ✅ **异常处理**：自动重试机制（最多3次）
- ✅ **断点续爬**：支持中断后继续爬取
- ✅ **数据清洗**：自动去重、清洗、格式化
- ✅ **双格式输出**：JSON（程序使用）+ Excel（人工查看）
- ✅ **完整日志**：详细的爬取和清洗日志

## 目录结构

```
crawler/
├── __init__.py              # 模块初始化
├── law_crawler.py           # 爬虫主程序
├── data_processor.py        # 数据清洗程序
└── README.md                # 使用说明

data/
├── raw/                     # 原始数据
│   ├── laws.json            # 爬取的原始数据
│   └── .crawl_checkpoint.json   # 断点续爬记录
└── processed/               # 清洗后的数据
    ├── laws.json            # JSON 格式（程序使用）
    └── laws.xlsx            # Excel 格式（人工查看）
```

## 使用方法

### 1. 爬取数据

```bash
# 默认爬取 200 部法律数据（预定义常用法律种子列表，找法网备用源自动补齐）
python crawler/law_crawler.py

# 小批量验证（先跑通流程、确认解析质量，再全量扩采）
python crawler/law_crawler.py --max 50

# 仅使用华律网，不启用找法网备用源
python crawler/law_crawler.py --no-backup

# 重新开始爬取（清除断点记录）
python crawler/law_crawler.py --reset

# 查看帮助
python crawler/law_crawler.py --help
```

### 2. 清洗数据

```bash
# 运行数据清洗
python crawler/data_processor.py
```

### 3. 在代码中使用

```python
from crawler import LawCrawler

# 创建爬虫实例
crawler = LawCrawler()

# 默认爬取 200 部（预定义种子列表 + 备用源补齐）
crawler.run()

# 小批量验证：先爬 50 部确认解析质量
# crawler.run(max_laws=50)

# 查看结果
print(f"爬取了 {len(crawler.laws)} 部法律数据")
```

## 采集字段

每条法律数据包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | str | 法律名称 |
| `level` | str | 效力层级（宪法/法律/行政法规/司法解释/地方性法规/部门规章） |
| `publish_date` | str | 发布日期 |
| `effective_date` | str | 施行日期 |
| `issuing_authority` | str | 发布机关 |
| `description` | str | 法律概述 |
| `clauses` | list | 条文列表 `[{clause_no, content}]` |
| `application_scenarios` | list | 适用场景/法律争议列表 |
| `related_cases` | list | 相关案例列表 `[{name, summary, court, result}]` |
| `source` | str | 数据来源（66law.cn / findlaw.cn） |
| `url` | str | 原始页面 URL |
| `crawled_at` | str | 爬取时间 |

## robots.txt 合规

### 华律网 (66law.cn)

需要检查 `https://www.66law.cn/robots.txt` 确认允许的路径。

**注意**：AI 爬虫（GPTBot、ClaudeBot 等）可能被禁止，请遵守站点规则。

### 找法网 (findlaw.cn)

需要检查 `https://www.findlaw.cn/robots.txt` 确认允许的路径。

## 爬虫礼仪

1. **请求频率**：每次请求间隔 3-5 秒
2. **User-Agent**：使用标准浏览器 User-Agent
3. **数据量**：单次爬取不超过 500 部
4. **用途**：仅用于学习和研究目的

## 常见问题

### Q: 爬虫中断了怎么办？

A: 直接重新运行即可，爬虫会自动从断点继续：

```bash
python crawler/law_crawler.py
```

### Q: 如何重新开始爬取？

A: 使用 `--reset` 参数：

```bash
python crawler/law_crawler.py --reset
```

### Q: 爬取的数据在哪里？

A:
- 原始数据：`data/raw/laws.json`
- 清洗后数据：`data/processed/laws.json`
- Excel 格式：`data/processed/laws.xlsx`

### Q: 如何查看爬取日志？

A: 日志文件在 `logs/crawler.log`

## 注意事项

⚠️ **法律合规**：
- 仅用于学习和研究目的
- 遵守 robots.txt 规则
- 不对目标网站造成过大访问压力
- 不用于商业用途

⚠️ **数据质量**：
- 爬取的数据可能存在不完整的情况
- 建议人工检查 Excel 文件确认数据质量
- 数据清洗会去除空值和重复数据
- 爬虫输出的法律内容仅供学习参考，不构成正式法律意见

## 技术栈

- `requests` - HTTP 请求
- `BeautifulSoup` - HTML 解析
- `tenacity` - 重试机制
- `pandas` - 数据处理
- `openpyxl` - Excel 导出
- `logging` - 日志记录
