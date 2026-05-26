import asyncio
import logging

import feedparser


class AlternativeDataProvider:
    def __init__(self, rss_urls: list[str] | None = None):
        self._logger = logging.getLogger("alternative_data")
        self.rss_urls = rss_urls or [
            "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^NSEI,^BSESN,RELIANCE.NS,TCS.NS,HDFCBANK.NS"
        ]

    async def fetch_latest_news(self) -> str:
        self._logger.debug("Fetching latest alternative data...")
        headlines = []
        try:
            for url in self.rss_urls:
                feed = await asyncio.to_thread(feedparser.parse, url)
                for entry in feed.entries[:10]:
                    # Some feeds only have title, some have summary
                    summary = getattr(entry, "summary", "")
                    headlines.append(f"- {entry.title} {summary}")

            if not headlines:
                return "No recent significant macro or geopolitical news available."
            return "\n".join(headlines)
        except Exception as e:
            self._logger.error("Error fetching alternative data: %s", e)
            return "Could not fetch alternative news data due to an error."
