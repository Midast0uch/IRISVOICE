"""Isolated test to verify patch.object works on CrawlOrchestrator._plan."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from unittest.mock import patch, AsyncMock
from backend.crawler.orchestrator import CrawlOrchestrator, get_crawl_orchestrator

class _Plan:
    urls = ["https://example.com/a"]
    instructions = "extract"
    result_type = "summary"
    title = "Test"

# Check singleton exists
orchestrator = get_crawl_orchestrator()
print("Singleton created:", id(orchestrator))
print("Before patch - _plan:", getattr(orchestrator, '_plan', 'NOT FOUND'))

with patch.object(CrawlOrchestrator, "_plan") as plan_mock:
    plan_mock.return_value = _Plan()
    print("After patch - _plan:", getattr(orchestrator, '_plan', 'NOT FOUND'))
    print("Is AsyncMock:", isinstance(orchestrator._plan, AsyncMock))
    # Call the patched method
    import asyncio
    async def test():
        result = await orchestrator._plan("test query")
        print("Result type:", type(result))
        print("Result urls:", result.urls if hasattr(result, 'urls') else 'NO URLS')
    asyncio.run(test())

print("After context - _plan:", getattr(orchestrator, '_plan', 'NOT FOUND'))
