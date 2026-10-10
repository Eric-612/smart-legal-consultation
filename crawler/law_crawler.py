#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SmartLegalConsultation - Web Crawler
Crawl law information from legal encyclopedia websites (66law.cn, findlaw.cn)
Follows robots.txt compliance and crawler etiquette
采集目标：法律名称、条文内容、适用场景、相关案例
"""

import os
import sys
import json
import time
import random
import logging
import hashlib
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin, urlparse
from typing import Optional
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# ===== Configuration =====

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)

# Output file
OUTPUT_FILE = DATA_RAW_DIR / "laws.json"
CHECKPOINT_FILE = DATA_RAW_DIR / ".crawl_checkpoint.json"

# Crawler settings
MAX_RETRIES = 3
REQUEST_TIMEOUT = 15
DELAY_MIN = 3.0  # Minimum delay between requests (seconds)
DELAY_MAX = 5.0  # Maximum delay between requests (seconds)

# Random User-Agent pool
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# ===== Predefined Law List =====
# Common laws for legal knowledge graph（66law.cn 法律百科拼音 slug）。
# 覆盖主要部门法领域：宪法/民法/刑法/程序法/劳动/婚姻家事/侵权/合同/消费者/公司/知产/行政/税/房产/环境/金融。
# 只允许 ASCII 拼音 slug；无效 slug 是可容忍的：仅计为失败请求，不影响整体（有 findlaw.cn 备份源兜底）。
COMMON_LAWS = [
    # 宪法
    "xianfa", "xianfazhengfaxiu", "guohuifa",
    # 民法总则/民法典
    "minfadian", "minfazongze", "minfahetongbian", "minfawuquanbian",
    "minfahunyinjiatingbian", "minfajichengbian", "minfaqinquanzerenbian", "minfarengeshenfenbian",
    # 刑法
    "xingfa", "xingfaxiuzheng", "xingfafudong", "xingfazongze", "xingfafenze",
    # 程序法
    "xingshisusongfa", "minshisusongfa", "xingzhengsusongfa", "zhongcifa", "renminminjian",
    "gongzhengfa", "lvsifa", "fayuanfa", "jianchaguanfa", "lifafa",
    # 劳动与社会保障
    "laodongfa", "laodonghetongfa", "laodonghetongfashishitiaoli", "shehuibaoxianfa",
    "gongshangbaoxiantiaoli", "shiyebaoxiantiaoli", "yiliaobaoxian", "zhigongdaidaijingjipeichangtiaoli",
    "laodongzhengyitiaojiezhongcaifa", "zuidigongziguding", "nvgonglaodongbaohuguiding",
    "quanguonianjiegongzuorenyuanjianxiaban", "gongzuoshijianxiuxi", "daixintuixiuyihuanzhijia",
    # 婚姻家事与未成年人
    "hunyindengjitiaoli", "fanjiatingbaolifa", "weichengnianrenbaohufa", "funvquanyibaozhangfa",
    "laonianrenquanyibaozhangfa", "jiyangfa", "shouyangfa", "jiatingjiaoyucujinfa", "weijiayi",
    # 侵权与损害赔偿
    "qinquanzerenfa", "daolufangquanshigu", "renshisunhaipeshang", "qinquanzeren",
    # 合同与商事
    "hetongfa", "zhaobiaotoubiao", "zhengfucaigoufa", "dianzishangwufa", "guanggaofa",
    "jiagefa", "fanlongduanfa", "fanbuzhengdangjingzhengfa", "fangdichanguanggao",
    # 消费者与产品质量
    "xiaofeizhequanyibaohufa", "chanpinzhiliangfa", "shipinanquanfa", "wuqimingzhi",
    # 公司与合伙企业
    "gongsifa", "hehuoqiyefa", "gerenduzigongsi", "gongsifashishitiaoli",
    # 知识产权
    "zhuanlifa", "shangbiaofa", "zhuzuoquanfa", "zhuzuoquanfashishitiaoli",
    "jisuanjiruanjianbaohutiaoli", "fanbuzhengdangjingzheng",
    # 行政与处罚
    "xingzhengchufafa", "xingzhengfuyifa", "xingzhengxukefa", "guojiapeichangfa",
    "xingzhengguanlifalianfaanjian", "xingzhengqiangzhi", "xingzhengchengxu",
    # 税
    "qiyesuodeshuifa", "gerensuodeshuifa", "zengzhishuishixingtiaoli", "yingshui",
    # 房产与土地
    "fangdichanguanlifa", "tudiguanlifa", "chengshifangdichanguanlifa", "jianzhufa",
    "fangwuzulin", "wuyeguanlitiaoli", "fangwumaishoutiaoli",
    # 环境
    "huanjingbaohufa", "dashengyanwu", "shuiwuran", "zaoshengwuran", "guidian",
    # 金融与保险
    "baoxianfa", "zhengquanfa", "shangyeyinhangfa", "zhongguorenminyinhangfa", "jijinfa",
    "xintuofa", "piaojufa", "haishangfa",
    # 治安与刑法相关
    "zhiansheli", "chuliangan", "shehuanzhixufa", "daolujiaotonganquanfa",
    "jisheng", "jishengjianfa", "yihuanfa", "xueyu", "baoli",
    # 特别/其他
    "nengyuan", "dianli", "shuidian", "qiyongchanquan", "xiangzhenqiye",
    "wailuyan", "wailizhiyuan", "duiwai", "haiwaitouzizhe", "waiguotouzifa",
    "jinkou", "chubai", "guanshui", "baoguan", "jiaoyifa", "jiaoyi",
    "gongwuyuanfa", "gongwuyuan", "jigoubianzhi", "shijian", "dangwu",
    "muzhang", "nongmin", "nongcun", "tudi", "jianshe", "chengxiang",
    "rengongzhineng", "shujuanquanfa", "wangluoanquanfa", "shujuanquan",
    "gerenxinxibaohufa", "wangluojiaoyi", "wangluo", "dianshang",
    # 学生/教育/劳动实习
    "jiaoyufa", "yiwujiaoyufa", "gaodengjiaoyufa", "jiaoshifa", "xueqianjiaoyu",
]

# 修正 COMMON_LAWS 中误写项（内部去噪）
COMMON_LAWS = [x.strip().replace(" ", "") for x in COMMON_LAWS if x.strip()]


# Generate full URLs from law slugs (deduplicated, order preserved)
def get_predefined_urls() -> list:
    """Generate full 66law.cn URLs from predefined law slugs"""
    seen, urls = set(), []
    for law_id in COMMON_LAWS:
        if law_id in seen:
            continue
        seen.add(law_id)
        urls.append(f"https://www.66law.cn/laws/{law_id}.aspx")
    return urls

# ===== Logging Setup =====

log_dir = PROJECT_ROOT / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "crawler.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# ===== Robots.txt Checker =====

class RobotsChecker:
    """Check if a URL is allowed by robots.txt"""

    def __init__(self):
        self.parsers = {}

    def get_parser(self, base_url: str) -> RobotFileParser:
        """Get or create a robots.txt parser for a domain"""
        if base_url not in self.parsers:
            rp = RobotFileParser()
            robots_url = urljoin(base_url, "/robots.txt")
            rp.set_url(robots_url)
            try:
                rp.read()
                logger.info(f"[OK] Loaded robots.txt from {robots_url}")
            except Exception as e:
                logger.warning(f"[WARN] Failed to load robots.txt from {robots_url}: {e}")
                # If we can't read robots.txt, allow everything (be conservative)
                rp.allow_all = True
            self.parsers[base_url] = rp
        return self.parsers[base_url]

    def is_allowed(self, url: str, user_agent: str = "*") -> bool:
        """Check if a URL is allowed by robots.txt"""
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        rp = self.get_parser(base_url)

        if hasattr(rp, "allow_all"):
            return True

        return rp.can_fetch(user_agent, url)

    def get_crawl_delay(self, base_url: str, user_agent: str = "*") -> Optional[float]:
        """Get the crawl delay specified in robots.txt"""
        rp = self.get_parser(base_url)
        try:
            delay = rp.crawl_delay(user_agent)
            return float(delay) if delay else None
        except Exception:
            return None


# ===== Crawler Class =====

class LawCrawler:
    """Crawl law information from legal encyclopedia websites"""

    def __init__(self):
        self.session = requests.Session()
        self.robots_checker = RobotsChecker()
        self.crawled_urls = set()
        self.laws = []
        self.stats = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
        }
        self._load_checkpoint()

    def _get_headers(self) -> dict:
        """Get random headers for each request"""
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }

    def _delay(self):
        """Wait a random delay between requests"""
        delay = random.uniform(DELAY_MIN, DELAY_MAX)
        time.sleep(delay)

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.RequestException, ConnectionError)),
    )
    def _fetch(self, url: str) -> Optional[str]:
        """Fetch a URL with retry logic"""
        # Check robots.txt first
        if not self.robots_checker.is_allowed(url):
            logger.warning(f"[BLOCKED] robots.txt disallows: {url}")
            return None

        logger.info(f"[FETCH] {url}")
        response = self.session.get(
            url,
            headers=self._get_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        response.encoding = response.apparent_encoding or "utf-8"
        return response.text

    def _load_checkpoint(self):
        """Load checkpoint to resume crawling"""
        if CHECKPOINT_FILE.exists():
            try:
                with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.crawled_urls = set(data.get("crawled_urls", []))
                self.laws = data.get("laws", [])
                self.stats = data.get("stats", self.stats)
                logger.info(
                    f"[RESUME] Loaded checkpoint: {len(self.crawled_urls)} URLs crawled, "
                    f"{len(self.laws)} laws collected"
                )
            except Exception as e:
                logger.warning(f"[WARN] Failed to load checkpoint: {e}")

    def _save_checkpoint(self):
        """Save checkpoint for resume"""
        try:
            with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "crawled_urls": list(self.crawled_urls),
                        "laws": self.laws,
                        "stats": self.stats,
                        "timestamp": datetime.now().isoformat(),
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            logger.error(f"[ERROR] Failed to save checkpoint: {e}")

    def _save_results(self):
        """Save final results to JSON"""
        try:
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "metadata": {
                            "source": "66law.cn + findlaw.cn",
                            "crawled_at": datetime.now().isoformat(),
                            "total_laws": len(self.laws),
                        },
                        "laws": self.laws,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            logger.info(f"[SAVED] {len(self.laws)} laws saved to {OUTPUT_FILE}")
        except Exception as e:
            logger.error(f"[ERROR] Failed to save results: {e}")

    # ===== 66law.cn Crawlers（主源：华律网法律百科）=====

    def crawl_66law_list(self) -> list:
        """Crawl law list from 66law.cn

        Note: The list page only shows popular laws.
        For a complete list, we rely on the predefined seed list + backup source.
        """
        logger.info("=" * 60)
        logger.info("[START] Crawling 66law.cn law list")
        logger.info("=" * 60)

        law_urls = []
        list_url = "https://www.66law.cn/laws/"

        try:
            html = self._fetch(list_url)
            if not html:
                return law_urls

            soup = BeautifulSoup(html, "html.parser")

            # Find all law links matching pattern: laws/<law_id>.aspx
            import re
            all_hrefs = [a.get("href", "") for a in soup.find_all("a", href=True)]

            for href in all_hrefs:
                match = re.search(r'/laws/([^/]+)\.aspx', href)
                if match:
                    law_id = match.group(1)
                    detail_url = f"https://www.66law.cn/laws/{law_id}.aspx"
                    if detail_url not in self.crawled_urls and detail_url not in law_urls:
                        law_urls.append(detail_url)

            logger.info(f"[LIST] Found {len(law_urls)} law URLs from 66law.cn")

        except Exception as e:
            logger.error(f"[ERROR] Failed to crawl law list: {e}")

        return law_urls

    def crawl_66law_detail(self, url: str) -> Optional[dict]:
        """Crawl law detail from 66law.cn

        URL format: https://www.66law.cn/laws/<law_id>.aspx
        采集字段：法律名称、效力层级、条文内容（clauses）、适用场景、相关案例。
        """
        try:
            html = self._fetch(url)
            if not html:
                return None

            soup = BeautifulSoup(html, "html.parser")
            law = {"source": "66law.cn", "url": url, "crawled_at": datetime.now().isoformat()}

            # Extract law name from H1 or title
            h1_tag = soup.find("h1")
            if h1_tag:
                law["name"] = h1_tag.get_text(strip=True)
            else:
                title_tag = soup.find("title")
                if title_tag:
                    title_text = title_tag.get_text(strip=True)
                    # Title format: "中华人民共和国劳动合同法 - 华律网"
                    law["name"] = title_text.split(" - ")[0].strip() if " - " in title_text else title_text

            if not law.get("name"):
                return None

            page_text = soup.get_text()
            import re

            # 效力层级：优先显式"效力级别/效力位阶"标签，其次从名称关键词推断
            level_patterns = [
                r'效力(?:级别|位阶|等级)[：:]\s*([^\n，。;；]{2,20})',
                r'法律效力[：:]\s*([^\n，。;；]{2,20})',
            ]
            level = ""
            for pattern in level_patterns:
                m = re.search(pattern, page_text)
                if m:
                    level = m.group(1).strip()
                    break
            if not level:
                if "宪法" in law["name"]:
                    level = "宪法"
                elif "条例" in law["name"]:
                    level = "行政法规"
                elif "司法解释" in law["name"]:
                    level = "司法解释"
                elif "法" in law["name"]:
                    level = "法律"
                else:
                    level = "法律"
            law["level"] = level

            # 发布/施行日期
            date_patterns = [
                r'(?:公布|发布)日期[：:]?\s*([0-9]{4}[-年.]\d{1,2}[-月.]\d{1,2}日?)',
                r'(?:施行|生效)日期[：:]?\s*([0-9]{4}[-年.]\d{1,2}[-月.]\d{1,2}日?)',
                r'([0-9]{4})年([0-9]{1,2})月([0-9]{1,2})日',
            ]
            m = re.search(date_patterns[0], page_text)
            if m:
                law["publish_date"] = m.group(1)
            m = re.search(date_patterns[1], page_text)
            if m:
                law["effective_date"] = m.group(1)
            if not law.get("publish_date") and not law.get("effective_date"):
                m = re.search(date_patterns[2], page_text)
                if m:
                    law["publish_date"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

            # 发布机关
            m = re.search(r'(?:发布|制定)机关[：:]\s*([^\n，。;；]{2,30})', page_text)
            if m:
                law["issuing_authority"] = m.group(1).strip()

            # 描述：优先最长正文 <p> 段（排除导航/推广文案）
            boilerplate = ("华律", "copyright", "咨询", "热线", "版权所有", "在线", "律师")
            best = ""
            for tag in soup.find_all("p"):
                txt = tag.get_text(strip=True)
                if 50 <= len(txt) <= 600 and len(txt) > len(best) \
                        and not any(k in txt for k in boilerplate):
                    best = txt
            if best:
                law["description"] = best[:500]

            # 条文内容：按"第X条"逐条提取（正则切分页面文本）
            clauses = []
            clause_blocks = re.split(r'(第[一二三四五六七八九十百千万零〇0-9]+条)', page_text)
            # clause_blocks 形如 [前文, "第一条", "内容", "第二条", "内容", ...]
            for i in range(1, len(clause_blocks) - 1, 2):
                clause_no = clause_blocks[i].strip()
                content = clause_blocks[i + 1].strip()
                # 截断到下一个明显栏目边界，控制长度
                content = re.split(r'(适用范围|适用场景|相关案例|案例分析|咨询|相关法律|推荐律师)', content)[0]
                content = content[:300].strip()
                if content and 2 < len(content) < 300:
                    clauses.append({"clause_no": clause_no, "content": content})
                if len(clauses) >= 20:
                    break
            if clauses:
                law["clauses"] = clauses

            # 适用场景（法律争议）：关键词定位后的句段
            scenarios = []
            m = re.search(r'(?:适用场景|适用范围|解决(?:的)?问题|主要解决)[：:]\s*([^\n]{1,200})', page_text)
            if m:
                scenario_text = m.group(1)
                scenarios = [
                    s.strip() for s in re.split(r'[、，,；;]', scenario_text)
                    if 1 < len(s.strip()) <= 20
                ]
            law["application_scenarios"] = scenarios[:10]

            # 相关案例：关键词定位后的案件名片段
            cases = []
            m = re.search(r'(?:相关案例|典型案例|案例)[：:]\s*([^\n]{1,300})', page_text)
            if m:
                case_text = m.group(1)
                raw_names = [s.strip() for s in re.split(r'[、，,；;]', case_text) if s.strip()]
                for raw in raw_names[:5]:
                    cases.append({"name": raw[:60]})
            law["related_cases"] = cases

            return law

        except Exception as e:
            logger.error(f"[ERROR] Failed to crawl {url}: {e}")
            return None

    # ===== findlaw.cn Crawlers (Backup) =====

    def crawl_findlaw_list(self) -> list:
        """Crawl law list from findlaw.cn as backup source."""
        logger.info("=" * 60)
        logger.info("[START] Crawling findlaw.cn law list (backup source)")
        logger.info("=" * 60)

        law_urls = []
        list_url = "https://www.findlaw.cn/law/"

        try:
            html = self._fetch(list_url)
            if not html:
                return law_urls

            import re
            ids = set(re.findall(r'/law/(\d+)\.html', html))
            law_urls = [
                f"https://www.findlaw.cn/law/{page_id}.html"
                for page_id in sorted(ids)
                if f"https://www.findlaw.cn/law/{page_id}.html" not in self.crawled_urls
            ]
            logger.info(f"[LIST] Found {len(law_urls)} law URLs from findlaw.cn")

        except Exception as e:
            logger.error(f"[ERROR] Failed to crawl findlaw.cn list: {e}")

        return law_urls

    def crawl_findlaw_detail(self, url: str) -> Optional[dict]:
        """Crawl law detail from findlaw.cn（备份源）"""
        try:
            html = self._fetch(url)
            if not html:
                return None

            import re
            soup = BeautifulSoup(html, "html.parser")
            law = {"source": "findlaw.cn", "url": url, "crawled_at": datetime.now().isoformat()}

            # 名称：H1 或 <title> 首段
            h1_tag = soup.find("h1")
            if h1_tag:
                law["name"] = h1_tag.get_text(strip=True)
            if not law.get("name"):
                title_tag = soup.find("title")
                if title_tag:
                    seg = title_tag.get_text(strip=True).split("_")[0]
                    law["name"] = re.sub(r"(全文|_找法网|法律|法规)$", "", seg).strip()
            if not law.get("name"):
                return None

            page_text = soup.get_text()

            # 效力层级
            m = re.search(r"(?:效力|级别|位阶)[：:]\s*([^\n]{1,20}?)(?:\s{2,}|$)", page_text)
            if m:
                law["level"] = m.group(1).strip().rstrip("，。、 ")
            else:
                law["level"] = "法律"

            # 条文内容
            clauses = []
            clause_blocks = re.split(r'(第[一二三四五六七八九十百千万零〇0-9]+条)', page_text)
            for i in range(1, len(clause_blocks) - 1, 2):
                clause_no = clause_blocks[i].strip()
                content = clause_blocks[i + 1].strip()
                content = re.split(r'(适用|案例|咨询|相关法律|推荐律师)', content)[0]
                content = content[:300].strip()
                if content and 2 < len(content) < 300:
                    clauses.append({"clause_no": clause_no, "content": content})
                if len(clauses) >= 20:
                    break
            if clauses:
                law["clauses"] = clauses

            # 适用场景
            scenarios = []
            m = re.search(r"(?:适用场景|适用范围)[：:]\s*([^\n]{1,200})", page_text)
            if m:
                scenarios = [
                    s.strip() for s in re.split(r"[、，,；;]", m.group(1))
                    if 1 < len(s.strip()) <= 20
                ]
            law["application_scenarios"] = scenarios[:10]

            # 描述：首个 50–500 字正文段落
            for block in soup.get_text("\n").split("\n"):
                block = block.strip()
                if 50 < len(block) < 500 and block != law.get("name"):
                    law["description"] = block
                    break

            return law

        except Exception as e:
            logger.error(f"[ERROR] Failed to crawl {url}: {e}")
            return None

    # ===== Main Crawl Logic =====

    def run(self, max_laws: int = 200, use_backup: bool = True, use_predefined: bool = True):
        """
        Run the crawler

        Args:
            max_laws: Maximum number of laws to crawl
            use_backup: Whether to use findlaw.cn as backup source (default ON)
            use_predefined: Whether to use predefined law list (recommended)
        """
        logger.info("=" * 60)
        logger.info(f"[START] Law Crawler started at {datetime.now().isoformat()}")
        logger.info(f"[CONFIG] Max laws: {max_laws}, Backup: {use_backup}, Predefined: {use_predefined}")
        logger.info("=" * 60)

        # Step 1: URLs = 预定义列表 ∪ 列表页发现（去重、保序），两路互补
        if use_predefined:
            predefined_urls = get_predefined_urls()
            logger.info(f"[LIST] Predefined law list: {len(predefined_urls)} slugs")
            list_urls = self.crawl_66law_list()
            urls = list(dict.fromkeys(predefined_urls + list_urls))
            logger.info(f"[LIST] Total 66law URLs (predefined + list page): {len(urls)}")
        else:
            # Fallback: crawl from 66law.cn list page only
            urls = self.crawl_66law_list()

        for url in urls:
            if len(self.laws) >= max_laws:
                break

            if url in self.crawled_urls:
                self.stats["skipped"] += 1
                continue

            law = self.crawl_66law_detail(url)
            if law and law.get("name"):
                self.laws.append(law)
                self.crawled_urls.add(url)
                self.stats["success"] += 1
                logger.info(
                    f"[OK] [{len(self.laws)}/{max_laws}] "
                    f"{law['name']} - {len(law.get('clauses', []))} clauses"
                )
            else:
                self.stats["failed"] += 1

            self.stats["total"] += 1
            self._save_checkpoint()
            self._delay()

        # Step 2: Crawl from findlaw.cn (backup source)
        if use_backup and len(self.laws) < max_laws:
            backup_urls = self.crawl_findlaw_list()

            for url in backup_urls:
                if len(self.laws) >= max_laws:
                    break

                if url in self.crawled_urls:
                    self.stats["skipped"] += 1
                    continue

                law = self.crawl_findlaw_detail(url)
                if law and law.get("name"):
                    self.laws.append(law)
                    self.crawled_urls.add(url)
                    self.stats["success"] += 1
                    logger.info(
                        f"[OK] [{len(self.laws)}/{max_laws}] "
                        f"{law['name']} (findlaw)"
                    )
                else:
                    self.stats["failed"] += 1

                self.stats["total"] += 1
                self._save_checkpoint()
                self._delay()

        # Step 3: Save results
        self._save_results()

        # Step 4: Print summary
        logger.info("=" * 60)
        logger.info("[COMPLETE] Crawl Summary:")
        logger.info(f"  Total requests: {self.stats['total']}")
        logger.info(f"  Success: {self.stats['success']}")
        logger.info(f"  Failed: {self.stats['failed']}")
        logger.info(f"  Skipped (already crawled): {self.stats['skipped']}")
        logger.info(f"  Laws collected: {len(self.laws)}")
        logger.info(f"  Output: {OUTPUT_FILE}")
        logger.info("=" * 60)


# ===== Main Entry =====

def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Legal Website Crawler")
    parser.add_argument(
        "--max", type=int, default=200, help="Maximum number of laws to crawl (default: 200)"
    )
    parser.add_argument(
        "--no-backup", action="store_true",
        help="Disable findlaw.cn backup source (backup is ON by default)",
    )
    parser.add_argument(
        "--reset", action="store_true", help="Reset checkpoint and start fresh"
    )
    parser.add_argument(
        "--no-predefined", action="store_true",
        help="Don't use predefined law list (crawl from website list page only)"
    )

    args = parser.parse_args()

    if args.reset and CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        logger.info("[RESET] Checkpoint file deleted, starting fresh")

    crawler = LawCrawler()
    crawler.run(
        max_laws=args.max,
        use_backup=not args.no_backup,
        use_predefined=not args.no_predefined
    )


if __name__ == "__main__":
    main()
