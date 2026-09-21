"""Debug script to trace TASK_PROGRESS emission from _execute_crawler_query."""
import asyncio
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))  # project root
from unittest.mock import patch, AsyncMock

from backend.agent.event_bus import get_event_bus, IRISStreamEvent

events = []
bus = get_event_bus()
bus.subscribe(IRISStreamEvent.TASK_PROGRESS, lambda p: events.append(('tp', dict(p.data or {}))))
bus.subscribe(IRISStreamEvent.LISTENING_STATE, lambda p: events.append(('ls', dict(p.data or {}))))

async def _fake_run(query, urls, instructions, on_page_done=None,
                    max_pages=5, delay_ms=1000, timeout_s=90.0, **kwargs):
    print(f"_fake_run called, on_page_done={on_page_done is not None}")
    if on_page_done:
        print("calling on_page_done...")
        on_page_done('https://example.com/a', 1, 2)
        on_page_done('https://example.org/b', 2, 2)
        print("on_page_done calls done")
    from backend.crawler.crawler_engine import CrawlResult, PageData
    return CrawlResult(
        query=query,
        pages=[PageData(url='https://example.com/a', title='Example',
                        markdown='content', html='<html></html>', metadata={})],
        duration_ms=10, crawled_at='2026-01-01T00:00:00+00:00',
    )

from backend.agent.tool_bridge import AgentToolBridge
bridge = AgentToolBridge.__new__(AgentToolBridge)
with patch('backend.crawler.crawl_runner.run_crawl_subprocess', _fake_run):
    with patch('backend.agent.inference.router.get_global_internet_access', return_value=True):
        result = asyncio.run(bridge._execute_crawler_query({'query': 'test'}, 'sess-1'))

print("\n=== Events ===")
for ev in events:
    print(f"  {ev[0]}: {ev[1]}")
tp_count = len([e for e in events if e[0] == 'tp'])
print(f"\nTASK_PROGRESS count: {tp_count}")
print(f"LISTENING_STATE count: {len([e for e in events if e[0] == 'ls'])}")
