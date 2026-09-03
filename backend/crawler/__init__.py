"""
IRIS Headless Web Crawler — Domain 14, Phase C
Uses Crawl4AI (AsyncWebCrawler + BM25ContentFilter) for headless crawling.
No separate browser process, no CDP port management.
"""
from .robots_checker import RobotsChecker, get_robots_checker
from .crawler_engine import CrawlerEngine, CrawlResult, PageData
from .crawl_planner import CrawlPlanner, CrawlPlan, get_crawl_planner
from .data_extractor import DataExtractor, get_data_extractor

__all__ = [
    "RobotsChecker", "get_robots_checker",
    "CrawlerEngine", "CrawlResult", "PageData",
    "CrawlPlanner", "CrawlPlan", "get_crawl_planner",
    "DataExtractor", "get_data_extractor",
]
