"""
Jarvis Web Tools — search and web interaction using DuckDuckGo and Selenium.
All tools use StructuredTool + Pydantic schemas for proper JSON schema generation.
All tools self-register into TOOL_REGISTRY.
"""
import logging
import time
import os
import json
from typing import Optional, List

from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from app.tool_registry import register_tool

logger = logging.getLogger("Jarvis")

# ===========================
# PYDANTIC SCHEMAS
# ===========================

class WebSearchSchema(BaseModel):
    query: str = Field(description="The search term or question to look up.")
    max_results: int = Field(default=5, description="Number of results to return (max 10).")

class ReadWebsiteSchema(BaseModel):
    url: str = Field(description="The full URL of the website to read.")

# ===========================
# 1. SEARCH WEB
# ===========================

def _search_web_func(query: str, max_results: int = 5) -> str:
    """Search the web for real-time information with news fallback."""
    try:
        from duckduckgo_search import DDGS
        
        # Clean query
        q = query.strip()
        search_query = q
        
        # Detect if user is looking for a match result/news
        is_news_likely = any(kw in q.lower() for kw in ["won", "match", "score", "vs", "versus", "yesterday", "today", "news", "latest"])

        if is_news_likely:
            if "result" not in q.lower() and "score" not in q.lower():
                search_query += " result score"

        limit = min(max_results, 10)
        results = []
        
        with DDGS() as ddgs:
            # 1. Try News Search first if it looks like news/scores
            if is_news_likely:
                logger.info(f"Trying News search for: {q}")
                news_gen = ddgs.news(q, max_results=limit, region='wt-wt', safesearch='off')
                if news_gen:
                    for r in news_gen:
                        results.append({
                            "type": "NEWS",
                            "title": r.get("title", "No Title"),
                            "href": r.get("url", "#"),
                            "body": r.get("body", "No description available.")
                        })

            # 2. Try Text Search (always or as fallback)
            logger.info(f"Trying Text search for: {search_query}")
            text_gen = ddgs.text(search_query, max_results=limit, region='wt-wt', safesearch='off')
            if text_gen:
                for r in text_gen:
                    results.append({
                        "type": "WEB",
                        "title": r.get("title", "No Title"),
                        "href": r.get("href", "#"),
                        "body": r.get("body", "No description available.")
                    })
        
        if not results:
            return f"No results found for '{query}'. The match might not have happened yet or the event is too recent for indexing."

        # Filter duplicates (by URL)
        seen_urls = set()
        unique_results = []
        for r in results:
            if r["href"] not in seen_urls:
                unique_results.append(r)
                seen_urls.add(r["href"])

        output = f"Web Search Results for: {query}\n\n"
        for i, r in enumerate(unique_results[:limit], 1):
            rtype = f"[{r['type']}] " if r.get('type') else ""
            output += f"{i}. {rtype}{r['title']}\n"
            output += f"   URL: {r['href']}\n"
            output += f"   Snippet: {r['body']}\n\n"
            
        output += "TIP: If you need more details from a specific link, call read_website_content(url)."
        return output

    except Exception as e:
        logger.error(f"Web search error: {e}")
        return f"Error performing web search: {str(e)}"

search_web = StructuredTool.from_function(
    name="search_web",
    description="Search the web for real-time information, news, or answers. Returns a list of relevant websites with titles, URLs, and snippets.",
    func=_search_web_func,
    args_schema=WebSearchSchema,
)
register_tool("search_web", search_web, "LOW", "web")


# ===========================
# 2. READ WEBSITE CONTENT
# ===========================

def _read_website_content_func(url: str) -> str:
    """Extract text content from a website using a headless browser."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager

        opts = Options()
        opts.add_argument("--headless")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36")

        # Use webdriver-manager to ensure driver exists
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
        
        try:
            driver.set_page_load_timeout(30)
            driver.get(url)
            time.sleep(3) # Wait for JS/React/Vue to render
            
            # Simple text extraction
            body_text = driver.find_element("tag name", "body").text
            
            # Clean up extra whitespace
            lines = [line.strip() for line in body_text.splitlines() if line.strip()]
            clean_text = "\n".join(lines)

            if not clean_text:
                return f"Could not extract meaningful text from {url}. The site might be blocking headless access or require login."

            # Truncate to avoid context limit issues
            if len(clean_text) > 8000:
                clean_text = clean_text[:8000] + "\n\n... (Content truncated for brevity)"
                
            return f"--- Content of {url} ---\n\n{clean_text}"
            
        finally:
            driver.quit()
            
    except Exception as e:
        logger.error(f"Read website error: {e}")
        return f"Error reading website {url}: {str(e)}"

read_website_content = StructuredTool.from_function(
    name="read_website_content",
    description="Fetch and read the full text content of a specific webpage URL. Useful for deep dives after finding a link via search_web.",
    func=_read_website_content_func,
    args_schema=ReadWebsiteSchema,
)
register_tool("read_website_content", read_website_content, "LOW", "web")
