#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Legal Data Processor
Clean and process raw crawled legal data
"""

import json
import logging
import re
from pathlib import Path
from datetime import datetime
from collections import Counter

import pandas as pd

# ===== Configuration =====

PROJECT_ROOT = Path(__file__).parent.parent
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

INPUT_FILE = DATA_RAW_DIR / "laws.json"
OUTPUT_JSON = DATA_PROCESSED_DIR / "laws.json"
OUTPUT_XLSX = DATA_PROCESSED_DIR / "laws.xlsx"

# Logging setup
log_dir = PROJECT_ROOT / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "data_processor.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Law level standardization mapping
LAW_LEVEL_MAPPING = {
    "宪法": "宪法",
    "法律": "法律",
    "基本法律": "法律",
    "民法典": "法律",
    "行政法规": "行政法规",
    "国务院行政法规": "行政法规",
    "司法解释": "司法解释",
    "两高司法解释": "司法解释",
    "地方性法规": "地方性法规",
    "部门规章": "部门规章",
    "规章": "部门规章",
}


class DataProcessor:
    """Process and clean raw legal data"""

    def __init__(self):
        self.raw_data = []
        self.cleaned_data = []
        self.stats = {
            "total_raw": 0,
            "duplicates_removed": 0,
            "empty_removed": 0,
            "cleaned": 0,
        }

    def load_raw_data(self):
        """Load raw data from JSON file"""
        if not INPUT_FILE.exists():
            logger.error(f"[ERROR] Raw data file not found: {INPUT_FILE}")
            return False

        try:
            with open(INPUT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.raw_data = data.get("laws", [])
            self.stats["total_raw"] = len(self.raw_data)
            logger.info(f"[LOADED] {len(self.raw_data)} raw records")
            return True

        except Exception as e:
            logger.error(f"[ERROR] Failed to load raw data: {e}")
            return False

    def clean_text(self, text: str) -> str:
        """Clean text: remove extra spaces and special characters"""
        if not text:
            return ""

        # Remove extra whitespace
        text = " ".join(text.split())

        # Remove special characters (keep Chinese, English, numbers, punctuation,
        # and the hyphen in dates like 1993-10-31)
        text = re.sub(r'[^\w\s一-鿿，。、；：！？""''（）《》第条.\-]+', '', text)

        return text.strip()

    def standardize_level(self, level: str) -> str:
        """Standardize law level names"""
        if not level:
            return ""

        level = level.strip()

        # Check if it's in our mapping
        if level in LAW_LEVEL_MAPPING:
            return LAW_LEVEL_MAPPING[level]

        # Try to find a match
        for key, value in LAW_LEVEL_MAPPING.items():
            if key in level:
                return value

        # If no match, return as is (but cleaned)
        return self.clean_text(level)

    def clean_clauses(self, clauses: list) -> list:
        """Clean clause list: remove empty and duplicate clauses"""
        cleaned = []
        seen = set()

        for clause in clauses or []:
            clause_no = self.clean_text(clause.get("clause_no", ""))
            content = self.clean_text(clause.get("content", ""))

            if not clause_no or not content:
                continue

            key = f"{clause_no}:{content[:30]}"
            if key in seen:
                continue

            seen.add(key)
            cleaned.append({"clause_no": clause_no, "content": content})

        return cleaned

    def clean_cases(self, cases: list) -> list:
        """Clean related case list"""
        cleaned = []
        seen = set()

        for case in cases or []:
            name = self.clean_text(case.get("name", ""))

            if not name or len(name) < 4:
                continue

            if name in seen:
                continue

            seen.add(name)
            cleaned.append({
                "name": name,
                "summary": self.clean_text(case.get("summary", "")),
                "court": self.clean_text(case.get("court", "")),
                "result": self.clean_text(case.get("result", "")),
            })

        return cleaned

    def remove_duplicates(self):
        """Remove duplicate laws based on name"""
        seen_names = set()
        unique_data = []

        for law in self.raw_data:
            name = law.get("name", "").strip()

            if not name:
                self.stats["empty_removed"] += 1
                continue

            if name in seen_names:
                self.stats["duplicates_removed"] += 1
                continue

            seen_names.add(name)
            unique_data.append(law)

        self.raw_data = unique_data
        logger.info(
            f"[DEDUP] Removed {self.stats['duplicates_removed']} duplicates, "
            f"{self.stats['empty_removed']} empty records"
        )

    def clean_records(self):
        """Clean individual records"""
        cleaned = []

        for law in self.raw_data:
            cleaned_law = {
                "name": self.clean_text(law.get("name", "")),
                "level": self.standardize_level(law.get("level", "")),
                "publish_date": self.clean_text(law.get("publish_date", "")),
                "effective_date": self.clean_text(law.get("effective_date", "")),
                "issuing_authority": self.clean_text(law.get("issuing_authority", "")),
                "description": self.clean_text(law.get("description", "")),
                "clauses": self.clean_clauses(law.get("clauses", [])),
                "application_scenarios": [self.clean_text(s) for s in law.get("application_scenarios", []) if s],
                "related_cases": self.clean_cases(law.get("related_cases", [])),
                "source": law.get("source", "unknown"),
                "url": law.get("url", ""),
                "crawled_at": law.get("crawled_at", ""),
            }

            # Only keep records with at least a name
            if cleaned_law["name"]:
                cleaned.append(cleaned_law)
                self.stats["cleaned"] += 1

        self.cleaned_data = cleaned
        logger.info(f"[CLEAN] {len(cleaned)} records cleaned")

    def generate_statistics(self):
        """Generate data statistics"""
        if not self.cleaned_data:
            logger.warning("[WARN] No cleaned data to analyze")
            return

        # Count by source
        source_counter = Counter(d["source"] for d in self.cleaned_data)

        # Count by law level
        level_counter = Counter(d["level"] for d in self.cleaned_data if d["level"])

        # Count scenarios
        all_scenarios = []
        for d in self.cleaned_data:
            all_scenarios.extend(d["application_scenarios"])
        scenario_counter = Counter(all_scenarios)

        # Field coverage
        fields = ["level", "description", "clauses", "application_scenarios", "related_cases"]
        coverage = {}
        for field in fields:
            count = sum(1 for d in self.cleaned_data if d.get(field))
            coverage[field] = f"{count}/{len(self.cleaned_data)} ({count/len(self.cleaned_data)*100:.1f}%)"

        # Clause stats
        total_clauses = sum(len(d["clauses"]) for d in self.cleaned_data)
        total_cases = sum(len(d["related_cases"]) for d in self.cleaned_data)

        # Print statistics
        logger.info("=" * 60)
        logger.info("[STATS] Data Statistics:")
        logger.info(f"  Total records: {len(self.cleaned_data)}")
        logger.info(f"  By source: {dict(source_counter)}")
        logger.info(f"  By law level: {dict(level_counter)}")
        logger.info(f"  Total clauses: {total_clauses}")
        logger.info(f"  Total related cases: {total_cases}")
        logger.info(f"  Unique scenarios: {len(scenario_counter)}")
        logger.info(f"  Top 10 scenarios: {scenario_counter.most_common(10)}")
        logger.info(f"  Field coverage: {coverage}")
        logger.info("=" * 60)

        return {
            "total": len(self.cleaned_data),
            "by_source": dict(source_counter),
            "by_level": dict(level_counter),
            "total_clauses": total_clauses,
            "total_cases": total_cases,
            "unique_scenarios": len(scenario_counter),
            "top_scenarios": scenario_counter.most_common(10),
            "field_coverage": coverage,
        }

    def save_json(self):
        """Save cleaned data as JSON"""
        try:
            output = {
                "metadata": {
                    "processed_at": datetime.now().isoformat(),
                    "total_laws": len(self.cleaned_data),
                    "stats": self.stats,
                },
                "laws": self.cleaned_data,
            }

            with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)

            logger.info(f"[SAVED] JSON saved to {OUTPUT_JSON}")

        except Exception as e:
            logger.error(f"[ERROR] Failed to save JSON: {e}")

    def save_excel(self):
        """Save cleaned data as Excel for manual review"""
        try:
            # Convert to DataFrame
            df = pd.DataFrame(self.cleaned_data)

            # Convert list fields to strings for Excel
            df["clauses"] = df["clauses"].apply(
                lambda x: "；".join(f"{c['clause_no']} {c['content'][:40]}" for c in x) if x else ""
            )
            df["application_scenarios"] = df["application_scenarios"].apply(
                lambda x: "、".join(x) if x else ""
            )
            df["related_cases"] = df["related_cases"].apply(
                lambda x: "、".join(c["name"] for c in x) if x else ""
            )

            # Save to Excel
            with pd.ExcelWriter(OUTPUT_XLSX, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="Laws")

            logger.info(f"[SAVED] Excel saved to {OUTPUT_XLSX}")

        except Exception as e:
            logger.error(f"[ERROR] Failed to save Excel: {e}")

    def process(self):
        """Run the full processing pipeline"""
        logger.info("=" * 60)
        logger.info("[START] Data Processing Pipeline")
        logger.info("=" * 60)

        # Step 1: Load raw data
        if not self.load_raw_data():
            return False

        # Step 2: Remove duplicates
        self.remove_duplicates()

        # Step 3: Clean records
        self.clean_records()

        # Step 4: Generate statistics
        stats = self.generate_statistics()

        # Step 5: Save outputs
        self.save_json()
        self.save_excel()

        logger.info("=" * 60)
        logger.info("[COMPLETE] Data Processing Summary:")
        logger.info(f"  Raw records: {self.stats['total_raw']}")
        logger.info(f"  Duplicates removed: {self.stats['duplicates_removed']}")
        logger.info(f"  Empty removed: {self.stats['empty_removed']}")
        logger.info(f"  Cleaned records: {self.stats['cleaned']}")
        logger.info("=" * 60)

        return True


def main():
    """Main entry point"""
    processor = DataProcessor()
    success = processor.process()

    if success:
        print("\n[SUCCESS] Data processing completed!")
        print(f"  JSON output: {OUTPUT_JSON}")
        print(f"  Excel output: {OUTPUT_XLSX}")
        print(f"  Log file: {log_dir / 'data_processor.log'}")
    else:
        print("\n[FAILED] Data processing failed. Check logs for details.")


if __name__ == "__main__":
    main()
