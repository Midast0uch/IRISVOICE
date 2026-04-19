  
IRIS — Unified Master Spec  
Version: 3.1  
Status: Ready for Implementation  
Project: IRISVOICE  
Stack: Next.js (TypeScript) + Python FastAPI + WebSocket + Crawl4AI (headless)  
----  
Critical Architecture Update (v3.1)  
Crawler Technology Change: Lightpanda has been replaced with Crawl4AI. This eliminates the CDP server management, binary dependencies, and WSL2 complexity. Crawl4AI is a pure-Python library providing headless crawling with built-in LLM-ready Markdown output, anti-bot detection, and content filtering (BM25).  
Impact: No separate binary process to manage. Crawler is instantiated directly in Python via AsyncWebCrawler, runs headless via Playwright (managed internally), and outputs clean Markdown instead of raw HTML/DOM.  
----  
System Architecture (Updated)  
┌──────────────────────────────────────────────────────────────┐  
│                      IRIS Frontend                           │  
│                                                              │  
│  ┌─────────────────────┐    ┌────────────────────────────┐  │  
│  │     ChatView        │    │     Dashboard Wing         │  │  
│  │                     │    │                            │  │  
│  │  Normal mode:       │    │  ┌──────────────────────┐  │  │  
│  │  - chat bubbles     │    │  │  Tab Bar             │  │  │  
│  │  - suggestion pills │    │  │  [code][web][dash][+]│  │  │  
│  │                     │    │  └──────────────────────┘  │  │  
│  │  Dev mode:          │    │                            │  │  
│  │  - CLI skin         │    │  ┌──────────────────────┐  │  │  
│  │  - top bar          │    │  │  Active Tab Content  │  │  │  
│  │  - suggestion pills │    │  │                      │  │  │  
│  │    (terminal style) │    │  │  code / web /        │  │  │  
│  └─────────────────────┘    │  │  html / dashboard    │  │  │  
│                             │  └──────────────────────┘  │  │  
│                             └────────────────────────────┘  │  
└──────────────────────┬───────────────────────────────────────┘  
│ WebSocket + REST  
┌──────────────────────┴───────────────────────────────────────┐  
│                      IRIS Backend (FastAPI)                  │  
│                                                              │  
│  ┌──────────────────────────────────────────────────────┐   │  
│  │                  IRIS Gateway                        │   │  
│  │  Routes messages to: AgentKernel / Orchestrator /    │   │  
│  │  Crawler based on active mode and message type       │   │  
│  └──────────────────────────────────────────────────────┘   │  
│                                                              │  
│  ┌───────────────┐  ┌──────────────┐  ┌─────────────────┐  │  
│  │ AgentKernel   │  │ Orchestrator │  │ CrawlerEngine   │  │  
│  │ (normal mode) │  │ (dev mode)   │  │ (Crawl4AI)      │  │  
│  └───────────────┘  └──────┬───────┘  └────────┬────────┘  │  
│                             │                    │           │  
│                    ┌────────┴──────┐    ┌────────┴────────┐ │  
│                    │ CLI Registry  │    │ Crawl4AI        │ │  
│                    │ subprocess    │    │ AsyncWebCrawler │ │  
│                    │ manager       │    │ (Python lib)    │ │  
│                    └───────────────┘    └─────────────────┘ │  
└──────────────────────────────────────────────────────────────┘  
----  
Part 4 — Headless Web Crawler (Updated for Crawl4AI)  
4.1 Philosophy  
The crawler runs entirely as a headless background process using Crawl4AI. There is no browser window, no extra screen component, no CDP server to manage, and no separate binary process. Crawl4AI is instantiated directly as a Python class, runs headless Chromium via Playwright (managed internally), and outputs clean LLM-ready Markdown.  
The user sees nothing of the crawling process. Results appear as a visual dashboard tab in the wing.  
The ChatView gets a clean one-liner:  
Found 8 AI funding rounds from the last 30 days — see Dashboard →  
Plus suggestion pills:  
[ filter Series A only ]  [ sort by amount ]  [ export CSV ]  [ dig into OpenAI round ]  
No markdown walls. No raw HTML dumps. Structured, visual, actionable.  
4.2 When the Crawler Activates  
The orchestrator routes queries to the crawler when the user's intent is clearly about finding, comparing, or monitoring information from the web. Examples the brain model should recognize as crawler tasks:  
•  "find the latest AI funding rounds"  
•  "compare Tesla Model 3 vs Rivian R1T specs"  
•  "what are people saying about X on Hacker News"  
•  "get the pricing from [site]"  
•  "monitor [topic] for new developments"  
The brain model makes this routing decision using the same when_to_use descriptor system as CLI tools.  
4.3 Crawl4AI Setup  
Installation:  
pip install crawl4ai  
playwright install chromium  
  
Configuration:  
# backend/config.py additions  
CRAWL4AI_HEADLESS = True  # Always headless, no GUI  
CRAWL4AI_USER_AGENT = "IRIS-Agent/1.0 (research assistant; respectful crawling)"  
CRAWL4AI_DEFAULT_DELAY = 1000  # ms between requests  
CRAWL4AI_MAX_PAGES = 5  
CRAWL4AI_TIMEOUT = 10000  # ms per page  
  
Key advantages over Lightpanda:  
•  No separate binary to download or manage  
•  No CDP port conflicts or process lifecycle management  
•  Built-in anti-bot detection and proxy escalation  
•  Automatic Shadow DOM flattening and consent popup removal  
•  BM25 content filtering to extract only relevant sections  
•  Output is clean Markdown (not raw HTML)  
4.4 Crawler Engine  
# backend/crawler/crawler_engine.py  
  
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, BrowserConfig  
from crawl4ai.content_filter_strategy import BM25ContentFilter  
import asyncio  
  
class CrawlerEngine:  
    def __init__(self):  
        self.browser_config = BrowserConfig(  
            headless=True,  
            user_agent=settings.CRAWL4AI_USER_AGENT,  
            # No browser window, runs in background  
        )  
        self.crawler = None  
      
    async def __aenter__(self):  
        self.crawler = AsyncWebCrawler(config=self.browser_config)  
        await self.crawler.start()  
        return self  
      
    async def __aexit__(self, exc_type, exc_val, exc_tb):  
        if self.crawler:  
            await self.crawler.close()  
      
    async def crawl(  
        self,  
        query: str,              # original user query  
        urls: list[str],         # URLs to crawl (determined by planner)  
        instructions: str,       # what to extract (determined by planner)  
        max_pages: int = 5,  
        delay_ms: int = 1000  
    ) -> CrawlResult:  
        """  
        Crawls URLs using Crawl4AI with BM25 filtering based on query.  
        """  
        # Configure BM25 filter to extract only relevant content  
        content_filter = BM25ContentFilter(  
            query=query,  
            bm25_threshold=1.0  # Adjust based on desired relevance  
        )  
          
        run_config = CrawlerRunConfig(  
            content_filter=content_filter,  
            delay_between_requests=delay_ms,  
            page_timeout=settings.CRAWL4AI_TIMEOUT,  
            # Extract markdown, screenshots optional (off by default)  
            markdown=True,  
            screenshot=False,  
        )  
          
        pages = []  
        for url in urls[:max_pages]:  
            try:  
                result = await self.crawler.arun(url=url, config=run_config)  
                pages.append(PageData(  
                    url=url,  
                    title=result.metadata.get('title', ''),  
                    markdown=result.markdown,  # Clean LLM-ready markdown  
                    html=result.html if not result.markdown else None,  
                    metadata=result.metadata  
                ))  
            except Exception as e:  
                pages.append(PageData(  
                    url=url,  
                    error=str(e),  
                    title='',  
                    markdown='',  
                    metadata={}  
                ))  
          
        return CrawlResult(  
            query=query,  
            pages=pages,  
            duration_ms=...,  # calculate actual  
            crawled_at=datetime.utcnow().isoformat()  
        )  
  
class CrawlResult:  
    query: str  
    pages: list[PageData]  
    duration_ms: int  
    crawled_at: str  
  
class PageData:  
    url: str  
    title: str  
    markdown: str      # Primary output: clean LLM-ready text  
    html: str | None   # Fallback raw HTML if markdown fails  
    metadata: dict     # og tags, dates, authors, etc.  
    error: str | None  # If crawl failed for this URL  
  
4.5 Crawl Planner  
Before crawling, the brain model plans what to fetch:  
# backend/crawler/crawl_planner.py  
  
# Brain model receives:  
# - User query  
# - Current date  
# - Instructions to output JSON only  
  
# Brain outputs:  
# {  
#   "urls": ["https://...", "https://..."],   # 1-5 URLs to fetch  
#   "instructions": "Extract: company name, funding amount, round type, date, investor names",  
#   "result_type": "table" | "cards" | "metrics" | "mixed",  
#   "title": "AI Funding Rounds — Last 30 Days"  
# }  
  
4.6 Data Extractor  
After raw crawl results are collected, a second brain model call structures the data:  
# backend/crawler/data_extractor.py  
  
# Brain model receives:  
# - Original user query  
# - Markdown content from all crawled pages (already cleaned by Crawl4AI's BM25 filter)  
# - Extraction instructions from planner  
# - Instructions to output JSON only  
  
# Brain outputs structured DashboardData (see 4.7)  
  
Note: Because Crawl4AI outputs clean Markdown (not raw HTML), the Data Extractor works with semantically relevant text blocks rather than noise-filled HTML, significantly improving extraction accuracy.  
4.7 DashboardData Schema  
interface DashboardData {  
  title:      string  
  query:      string  
  timestamp:  string               // ISO date  
  summary:    string               // 1-2 sentence overview  
  sections:   DashboardSection[]  
}  
  
type DashboardSection =  
  | MetricsSection  
  | TableSection  
  | CardsSection  
  | ChartSection  
  
interface MetricsSection {  
  type:    'metrics'  
  items:   { label: string; value: string; delta?: string; trend?: 'up'|'down'|'flat' }[]  
}  
  
interface TableSection {  
  type:    'table'  
  title?:  string  
  headers: string[]  
  rows:    string[][]  
}  
  
interface CardsSection {  
  type:    'cards'  
  title?:  string  
  items:   { title: string; subtitle?: string; body: string; url?: string; tag?: string }[]  
}  
  
interface ChartSection {  
  type:       'chart'  
  title?:     string  
  chart_type: 'bar' | 'line' | 'pie'  
  labels:     string[]  
  datasets:   { label: string; values: number[] }[]  
}  
  
4.8 DashboardRenderer Component  
components/wing/DashboardRenderer.tsx  
  
Props:  
  data: DashboardData  
  
Renders:  
  - Title + query + timestamp header  
  - Summary line  
  - Each section in order:  
    - MetricsSection → row of KPI cards (value large, label small, delta colored)  
    - TableSection   → sortable table with alternating row shading  
    - CardsSection   → grid of cards (2-col on wide, 1-col on narrow)  
    - ChartSection   → Recharts bar/line/pie (Recharts already likely in project,  
                        or use lightweight chartist — avoid adding heavy deps)  
  - Footer: "Crawled N pages · X ms · Export [JSON] [CSV]"  
  
4.9 Export  
The dashboard footer provides two export buttons:  
JSON export: window.saveAs(new Blob([JSON.stringify(data, null, 2)], {type:'application/json'}), title.json)  
CSV export: Flatten all TableSection rows → CSV string → download. If multiple table sections, concatenate with section title as separator row.  
Both are client-side only. No backend call needed.  
4.10 Crawler WebSocket Messages  
Server → Client:  
// Crawler started (shown as a dim status line in ChatView dev mode, hidden in normal)  
{ type: 'crawler_started', query: string, url_count: number }  
  
// Each page as it is fetched (optional progress, shown in ChatView dim line)  
{ type: 'crawler_page_fetched', url: string, page_number: number, total: number }  
  
// Crawl complete — open dashboard tab in wing  
{  
  type:    'open_tab',  
  tab_type: 'dashboard',  
  id:      string,  
  title:   string,  
  data:    DashboardData  
}  
  
// Synthesis response for ChatView (clean one-liner + pills)  
{  
  type:        'text_response',  
  content:     string,        // e.g. "Found 8 funding rounds — see Dashboard →"  
  suggestions: Suggestion[]  
}  
  
// Error  
{ type: 'crawler_error', message: string }  
  
4.11 Robots.txt and Polite Crawling  
Crawl4AI respects robots.txt automatically via its internal Playwright implementation, but we add explicit checking:  
# backend/crawler/robots_checker.py  
# Uses urllib.robotparser  
# Cache robots.txt per domain for the session (don't refetch per page)  
# If disallowed: skip URL, log warning, include in summary as "blocked by robots.txt"  
  
Polite crawling defaults (all configurable via .env):  
CRAWLER_DELAY_MS=1000          # minimum delay between requests to same domain  
CRAWLER_MAX_PAGES=5            # maximum pages per crawl task  
CRAWLER_TIMEOUT_MS=10000       # per-page timeout  
CRAWLER_USER_AGENT=IRIS-Agent/1.0 (respectful crawler; contact: your@email.com)  
  
----  
Part 5 — New Files to Create (Updated)  
backend/  
└── dev/  
    ├── __init__.py  
    ├── orchestrator.py  
    ├── cli_registry.py  
    ├── subprocess_manager.py  
    ├── file_watcher.py  
    └── cli_tools.yaml  
  
backend/  
└── crawler/  
    ├── __init__.py  
    ├── crawler_engine.py      # Uses Crawl4AI (no lightpanda_manager.py needed)  
    ├── crawl_planner.py  
    ├── data_extractor.py  
    └── robots_checker.py  
  
components/  
├── chat/  
│   └── SuggestionPills.tsx  
└── wing/  
    ├── TabBar.tsx  
    ├── TabContent.tsx  
    └── DashboardRenderer.tsx  
  
hooks/  
├── useDevMode.ts  
└── useCrawler.ts  
  
types/  
└── iris.ts  
  
Removed: backend/crawler/lightpanda_manager.py (Crawl4AI manages browser lifecycle internally)  
----  
Part 6 — Files to Modify (Updated)  
File	What Changes  
`backend/main.py`	Init orchestrator on startup. Remove: LightpandaManager initialization. Mount new routers  
`backend/iris_gateway.py`	Route `dev_*` messages to orchestrator, crawler queries to crawler engine, intercept agent output for tab open events  
`backend/agent/agent_kernel.py`	Inject suggestion generation into every response via system prompt addition  
`components/features/ChatView.tsx`	Add `mode` prop, CLI skin conditional rendering, top bar (dev mode), mount SuggestionPills  
`components/dashboard/WingComponent.tsx`	Add TabBar + TabContent + dev panels (terminal output, file activity)  
`hooks/useIRISWebSocket.ts`	Forward `dev_*`, `crawler_*`, `open_tab`, `close_tab` to appropriate handlers  
`backend/state_manager.py`	Persist working directory, recent dirs, active dev mode state. Remove: Lightpanda state  
`.env`	Add: `DEV_ALLOWED_ROOTS`, `DEV_CLI_IDLE_TIMEOUT_SECONDS=300`, `CRAWLER_DELAY_MS=1000`, `CRAWLER_MAX_PAGES=5`, `CRAWLER_USER_AGENT`. Remove: `LIGHTPANDA_BIN`  
`requirements.txt`	Add: `watchdog`, `crawl4ai`, `playwright`. Remove: lightpanda references  
`package.json`	Add: `highlight.js`, `recharts` (if not already present)  
----  
Part 7 — Build Order (Updated)  
Follow this sequence exactly. Each step has no unresolved dependencies on later steps.  
1.  types/iris.ts  
    — all TypeScript interfaces: Tab, DashboardData, Suggestion, DevMode types  
  
2.  components/chat/SuggestionPills.tsx  
    — standalone component, mock data testable immediately  
  
3.  Modify ChatView.tsx  
    — add mode prop, CLI skin, top bar, mount SuggestionPills (UI only, no backend yet)  
  
4.  components/wing/TabBar.tsx + TabContent.tsx  
    — standalone, mock tab data testable immediately  
  
5.  components/wing/DashboardRenderer.tsx  
    — standalone, mock DashboardData testable immediately  
  
6.  Modify WingComponent.tsx  
    — integrate TabBar + TabContent + DashboardRenderer + dev panels  
  
7.  backend/dev/cli_registry.py + cli_tools.yaml  
    — no dependencies  
  
8.  backend/dev/subprocess_manager.py  
    — depends on cli_registry  
  
9.  backend/dev/file_watcher.py  
    — no dependencies  
  
10. backend/dev/orchestrator.py  
    — depends on cli_registry + subprocess_manager + file_watcher  
  
11. pip install crawl4ai playwright  
    playwright install chromium  
    — install crawler dependencies  
  
12. backend/crawler/robots_checker.py  
    — no dependencies  
  
13. backend/crawler/crawler_engine.py  
    — depends on crawl4ai library (installed in step 11) + robots_checker  
    — Note: No separate process manager needed, Crawl4AI handles browser internally  
  
14. backend/crawler/crawl_planner.py + data_extractor.py  
    — depends on agent_kernel (LLM call pattern already established)  
  
15. Modify backend/iris_gateway.py  
    — route dev_* to orchestrator, crawler queries to crawler, intercept open_tab events  
  
16. Modify backend/main.py  
    — init orchestrator on startup (remove lightpanda manager init)  
  
17. Modify backend/state_manager.py  
    — working directory + dev mode persistence  
  
18. hooks/useDevMode.ts + useCrawler.ts  
    — frontend hooks for new message types  
  
19. Modify hooks/useIRISWebSocket.ts  
    — forward to useDevMode and useCrawler  
  
20. Modify backend/agent/agent_kernel.py  
    — suggestion generation injection  
  
21. Integration test (see Part 8)  
  
----  
Part 8 — Testing Checklist (Updated)  
Suggestion Pills:  
•  [ ] Pills appear after every assistant response, both modes  
•  [ ] Maximum one active pill row visible at a time  
•  [ ] Pill morph animation plays smoothly into user bubble (layoutId transition)  
•  [ ] Selecting a pill sends the message and removes that pill row permanently  
•  [ ] Backdrop click dismisses without sending  
•  [ ] Dismissed rows never reappear on scroll  
•  [ ] Dev mode pills render with terminal aesthetic (monospace, > prefix)  
•  [ ] Suggestions are contextually relevant, not generic  
•  [ ] Suggestions never repeat what was just asked  
Developer Mode:  
•  [ ] </> toggle switches ChatView to CLI skin  
•  [ ] Monospace font applies throughout in dev mode  
•  [ ] User messages render as ❯ text not bubbles  
•  [ ] Top bar shows workdir, active tool, model  
•  [ ] Working directory persists across page refresh and mode toggle  
•  [ ] Orchestrator selects correct CLI tool for different task types  
•  [ ] CLI subprocess spawns in the correct working directory  
•  [ ] CLI stdout streams to wing terminal panel in real time  
•  [ ] CLI stdout does NOT appear raw in ChatView (only synthesized summary does)  
•  [ ] File activity panel updates as CLI modifies files  
•  [ ] Clicking file in activity panel opens it as a code tab  
•  [ ] Abort terminates subprocess cleanly  
•  [ ] Idle subprocess cleaned up after timeout  
•  [ ] Working directory outside allowed roots rejected with clear error  
Tabbed Wing:  
•  [ ] Tab bar appears only when at least one tab is open  
•  [ ] open_tab message with same id updates existing tab (does not duplicate)  
•  [ ] Closing a tab switches to adjacent tab automatically  
•  [ ] Tab transitions animate correctly (Framer Motion)  
•  [ ] Code tabs render with syntax highlighting  
•  [ ] Web tabs render iframe with correct sandbox attributes  
•  [ ] HTML tabs render srcDoc iframe  
•  [ ] Dashboard tabs render DashboardRenderer  
•  [ ] Modified indicator appears on code tabs written to this session  
Headless Crawler (Crawl4AI):  
•  [ ] pip install crawl4ai && playwright install chromium completes successfully  
•  [ ] No separate binary download or CDP server management required  
•  [ ] Crawler initializes as Python class (not external process)  
•  [ ] No browser window appears at any point (headless=True enforced)  
•  [ ] BM25 content filter extracts only query-relevant sections  
•  [ ] robots.txt checked before crawling each domain  
•  [ ] Disallowed URLs skipped, noted in summary  
•  [ ] Polite delay enforced between requests to same domain  
•  [ ] Dashboard tab opens in wing with structured results  
•  [ ] Output is clean Markdown (not raw HTML walls)  
•  [ ] MetricsSection renders as KPI cards  
•  [ ] TableSection renders as sortable table  
•  [ ] CardsSection renders as card grid  
•  [ ] ChartSection renders as chart  
•  [ ] Export JSON downloads valid JSON file  
•  [ ] Export CSV downloads valid CSV file  
•  [ ] Chat receives clean one-liner summary (not raw crawl data)  
•  [ ] Suggestion pills after crawl are refinement-oriented  
•  [ ] Crawler error surfaces as a chat message, not a silent failure  
•  [ ] Anti-bot detection handles consent popups automatically  
----  
Migration Notes (v3.0 → v3.1)  
If you started implementing v3.0 with Lightpanda:  
1.  Remove: backend/crawler/lightpanda_manager.py  
2.  Remove: LIGHTPANDA_BIN from .env  
3.  Install: pip install crawl4ai playwright && playwright install chromium  
4.  Update: crawler_engine.py to use AsyncWebCrawler class pattern instead of CDP connection  
5.  Simplify: No process lifecycle management needed (no start(), stop(), is_running() checks)  
6.  Benefit: Built-in BM25 filtering means less noise pre-processing in data_extractor.py  
The rest of the system (DashboardData schema, WebSocket messages, Frontend components) remains unchanged.  
  
*  
  
  
