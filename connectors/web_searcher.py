from typing import Dict, Optional, List, Iterable
import requests
import os
import itertools
import re

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

try:
    from ddgs import DDGS  # type: ignore
    DUCK_SEARCH_HINT = "Install with `pip install ddgs` to enable DuckDuckGo fallback."
except ImportError:
    try:
        from duckduckgo_search import DDGS  # type: ignore
        DUCK_SEARCH_HINT = "Install the renamed package with `pip install ddgs` to silence warnings."
    except ImportError:
        DDGS = None  # type: ignore
        DUCK_SEARCH_HINT = "Install DuckDuckGo search support with `pip install ddgs`."

try:
    from googlesearch import search as google_search  # type: ignore
    GOOGLE_SCRAPE_HINT = ""
except ImportError:
    google_search = None  # type: ignore
    GOOGLE_SCRAPE_HINT = "Install Google scrape fallback with `pip install googlesearch-python`."

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError:
    BeautifulSoup = None  # type: ignore

class WebSearcher:
    """Web search connector with privacy protection."""
    
    def __init__(self, cfg: Optional[Dict] = None, llm=None):
        self.cfg = cfg or {}
        self.llm = llm
        self.search_api_key = self.cfg.get("SEARCH_API_KEY") or os.environ.get("SEARCH_API_KEY")
        self.search_cx = self.cfg.get("SEARCH_CX") or os.environ.get("SEARCH_CX")
        self.serper_api_key = self.cfg.get("SERPER_API_KEY") or os.environ.get("SERPER_API_KEY")

    def search(self, query: str, num_results: int = 5) -> Dict:
        """Perform web search with privacy checks."""
        try:
            if self.llm:
                query = self.llm._redact_sensitive_info(query)

            google_result: Dict = {}
            if self.search_api_key and self.search_cx:
                google_result = self._search_google(query, num_results)
                if google_result.get("status") == "success":
                    return google_result
            else:
                google_result = {}

            serper_result: Dict = {}
            if self.serper_api_key:
                serper_result = self._search_serper(query, num_results)
                if serper_result.get("status") == "success":
                    return serper_result

            scrape_result: Dict = {}
            if google_search:
                scrape_result = self._search_google_scrape(query, num_results)
                if scrape_result.get("status") == "success":
                    return scrape_result

            ddg_result = self._search_duckduckgo(query, num_results)
            if ddg_result.get("status") == "success":
                return ddg_result

            error_candidates = [
                google_result.get("error") if google_result else None,
                serper_result.get("error") if serper_result else None,
                scrape_result.get("error") if scrape_result else None,
                ddg_result.get("error") if ddg_result else None,
            ]
            if not google_search and GOOGLE_SCRAPE_HINT:
                error_candidates.append(GOOGLE_SCRAPE_HINT)
            error_message = next((msg for msg in error_candidates if msg), None)
            return {
                "error": error_message or "Search failed",
                "status": "failed",
            }
        except requests.RequestException as exc:
            return {
                "error": f"Network error during search: {exc}",
                "status": "failed",
            }
        except Exception as exc:
            return {
                "error": str(exc),
                "status": "failed"
            }

    def _search_google(self, query: str, num_results: int) -> Dict:
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": self.search_api_key,
            "cx": self.search_cx,
            "q": query,
            "num": min(num_results, 10),
        }
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            error_detail = ""
            if response.headers.get("Content-Type", "").startswith("application/json"):
                try:
                    error_detail = response.json().get("error", {}).get("message", "")
                except ValueError:
                    error_detail = ""
            return {
                "error": f"Search API error: {response.status_code} {error_detail}".strip(),
                "status": "failed",
            }

        data = response.json()
        search_results = []
        for item in data.get("items", []):
            search_results.append(
                {
                    "title": item.get("title", ""),
                    "link": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                }
            )

        return {
            "query": query,
            "results": search_results[:num_results],
            "status": "success",
            "count": len(search_results),
            "source": "google",
        }

    def _search_serper(self, query: str, num_results: int) -> Dict:
        if not self.serper_api_key:
            return {
                "error": "Serper API key missing.",
                "status": "failed",
            }

        headers = {
            "X-API-KEY": self.serper_api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "q": query,
            "num": min(num_results, 10),
        }
        try:
            response = requests.post("https://google.serper.dev/search", json=payload, headers=headers, timeout=10)
        except requests.RequestException as exc:
            return {
                "error": f"Serper request failed: {exc}",
                "status": "failed",
            }

        if response.status_code != 200:
            detail = ""
            try:
                detail = response.json().get("message", "")
            except ValueError:
                detail = response.text[:200]
            return {
                "error": f"Serper API error: {response.status_code} {detail}".strip(),
                "status": "failed",
            }

        try:
            data = response.json()
        except ValueError as exc:
            return {
                "error": f"Invalid Serper response: {exc}",
                "status": "failed",
            }

        organics = data.get("organic") or []
        results: List[Dict[str, str]] = []
        for item in itertools.islice(organics, num_results):
            snippet = item.get("snippet") or ""
            if not snippet:
                highlights = item.get("snippetHighlighted")
                if isinstance(highlights, list):
                    snippet = " ... ".join(highlights)
            results.append(
                {
                    "title": item.get("title", ""),
                    "link": item.get("link") or item.get("url", ""),
                    "snippet": snippet,
                }
            )

        if not results:
            return {
                "error": "Serper returned no results",
                "status": "failed",
            }

        return {
            "query": query,
            "results": results,
            "status": "success",
            "count": len(results),
            "source": "google-serper",
        }

    def _search_google_scrape(self, query: str, num_results: int) -> Dict:
        if not google_search:
            return {
                "error": GOOGLE_SCRAPE_HINT,
                "status": "failed",
            }

        try:
            links: Iterable[str] = google_search(query, num_results=max(num_results, 10), stop=max(num_results, 10))
        except Exception as exc:
            return {
                "error": f"Google scrape failed: {exc}",
                "status": "failed",
            }

        items: List[Dict[str, str]] = []
        for url in itertools.islice(links, num_results):
            meta = self._fetch_page_metadata(url)
            items.append(
                {
                    "title": meta["title"],
                    "link": url,
                    "snippet": meta["snippet"],
                }
            )

        if not items:
            return {
                "error": "Google scrape returned no results",
                "status": "failed",
            }

        return {
            "query": query,
            "results": items,
            "status": "success",
            "count": len(items),
            "source": "google-scrape",
        }

    def _fetch_page_metadata(self, url: str) -> Dict[str, str]:
        title = url
        snippet = ""
        try:
            response = requests.get(url, headers=DEFAULT_HEADERS, timeout=5)
            if response.status_code != 200:
                return {"title": title, "snippet": snippet}

            html = response.text
            if BeautifulSoup:
                soup = BeautifulSoup(html, "html.parser")
                if soup.title and soup.title.string:
                    title = soup.title.string.strip()
                meta = soup.find("meta", attrs={"name": "description"})
                if not meta:
                    meta = soup.find("meta", attrs={"property": "og:description"})
                if meta and meta.get("content"):
                    snippet = meta["content"].strip()
            else:
                title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
                if title_match:
                    title = title_match.group(1).strip()
                desc_match = re.search(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
                if desc_match:
                    snippet = desc_match.group(1).strip()
        except Exception:
            return {"title": title, "snippet": snippet}

        return {"title": title or url, "snippet": snippet}

    def _search_duckduckgo(self, query: str, num_results: int) -> Dict:
        if not DDGS:
            return {
                "error": DUCK_SEARCH_HINT,
                "status": "failed",
            }

        items: List[Dict[str, str]] = []
        with DDGS() as ddgs:  # type: ignore
            try:
                results_iter = ddgs.text(query, max_results=max(num_results, 5))
                for result in itertools.islice(results_iter, num_results):
                    items.append(
                        {
                            "title": result.get("title", "").strip() or "(no title)",
                            "link": result.get("href", ""),
                            "snippet": result.get("body", "").strip(),
                        }
                    )
            except Exception as exc:
                return {
                    "error": f"DuckDuckGo search failed: {exc}",
                    "status": "failed",
                }

        if not items:
            return {
                "error": "DuckDuckGo returned no results",
                "status": "failed",
            }

        return {
            "query": query,
            "results": items,
            "status": "success",
            "count": len(items),
            "source": "duckduckgo",
        }
