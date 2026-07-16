"""
Web Search Tool - Search the web using Tavily AI via LangChain.
"""

import os
from typing import Dict, Any
from agent_harness.tool_registry import tool_registry


@tool_registry.register(category="search")
async def web_search(query: str, max_results: int = 5, search_depth: str = "basic") -> Dict[str, Any]:
    """
    Search the web using Tavily AI via LangChain.

    Args:
        query: Search query or question
        max_results: Number of results to return (default: 5)
        search_depth: "basic" (fast) or "advanced" (more detailed)

    Returns:
        Dict with search results:
        {
            "success": bool,
            "results": [{"title": str, "url": str, "content": str, "score": float}],
            "query": str,
            "error": str | None
        }
    """
    try:
        # Get API key from environment
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            return {
                "success": False,
                "results": [],
                "query": query,
                "error": "TAVILY_API_KEY not found in environment variables",
            }

        # Lazy import LangChain Tavily tool (new package)
        from langchain_tavily import TavilySearch

        # Initialize Tavily search tool
        search_tool = TavilySearch(max_results=max_results, search_depth=search_depth, api_key=api_key)

        # Perform search (LangChain tools are sync, so we call directly)
        raw_results = search_tool.invoke({"query": query})

        # Format results to consistent format
        # TavilySearch returns a dict with 'results' key
        results = []
        search_results = raw_results.get("results", []) if isinstance(raw_results, dict) else []

        for item in search_results:
            if isinstance(item, dict):
                results.append(
                    {
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "content": item.get("content", ""),
                        "score": item.get("score", 0.0),
                    }
                )

        return {"success": True, "results": results, "query": query, "error": None}

    except Exception as e:
        return {"success": False, "results": [], "query": query, "error": str(e)}
