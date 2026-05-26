import asyncio
import json
import logging
import os
import re
from typing import Any
import httpx

from src.agents.base import BaseAgent
from src.config.settings import settings
from src.schemas.events import Event, EventType, MacroSentimentEvent


class ExpertPersonasAgent(BaseAgent):
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(
        self,
        event_store=None,
        alternative_data_provider=None,
        api_key: str | None = None,
        poll_interval: int = 3600,
    ):
        super().__init__("personas", event_store=event_store)
        self._alt_data = alternative_data_provider
        self._api_key = api_key or settings.gemini_api_key or os.getenv("GEMINI_API_KEY", "")
        self._poll_interval = poll_interval
        self._task: asyncio.Task | None = None
        self.logger = logging.getLogger("agent.personas")

    async def on_start(self) -> None:
        self.logger.info("Expert Personas Agent initializing")
        if not self._alt_data:
            from src.connectors.alternative_data import AlternativeDataProvider
            self._alt_data = AlternativeDataProvider()

    async def on_event(self, event: Event) -> None:
        pass

    async def run_forever(self) -> None:
        self.logger.info("Starting Expert Personas background polling loop")
        self._task = asyncio.create_task(self._poll_loop())
        try:
            await super().run_forever()
        except asyncio.CancelledError:
            if self._task:
                self._task.cancel()
            raise

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self._evaluate_macro_sentiment()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in personas polling loop: %s", e)
            
            await asyncio.sleep(self._poll_interval)

    async def _evaluate_macro_sentiment(self) -> None:
        news_text = await self._alt_data.fetch_latest_news()
        
        if not self._api_key:
            self.logger.warning("No Gemini API Key. Using neutral fallback sentiment.")
            await self.emit(MacroSentimentEvent.create(
                geopolitical_score=0.0,
                macro_score=0.0,
                composite_multiplier=1.0,
                rationale="Fallback neutral sentiment due to missing LLM API key.",
                producer=self.name,
            ))
            return
            
        prompt = self._build_prompt(news_text)
        result = await self._call_gemini(prompt)
        
        if result:
            self.logger.info("Macro Sentiment Evaluated: %s", result.get("rationale", ""))
            await self.emit(MacroSentimentEvent.create(
                geopolitical_score=float(result.get("geopolitical_score", 0.0)),
                macro_score=float(result.get("macro_score", 0.0)),
                composite_multiplier=float(result.get("composite_multiplier", 1.0)),
                rationale=result.get("rationale", "No rationale provided"),
                producer=self.name,
            ))
        else:
            self.logger.error("Failed to evaluate sentiment, using neutral fallback.")
            await self.emit(MacroSentimentEvent.create(
                geopolitical_score=0.0,
                macro_score=0.0,
                composite_multiplier=1.0,
                rationale="Fallback neutral sentiment due to LLM error.",
                producer=self.name,
            ))

    def _build_prompt(self, news_text: str) -> str:
        return (
            "You are a dual-persona AI system for quantitative trading in India.\n"
            "Persona 1: Geopolitical Analyst (evaluates global tension, oil, US markets).\n"
            "Persona 2: Macro Economist (evaluates inflation, rates, Indian context).\n\n"
            "Here is the latest financial news:\n"
            f"{news_text}\n\n"
            "Analyze the news and provide a JSON response with exactly these fields:\n"
            "- geopolitical_score: float from -1.0 (very bearish) to 1.0 (very bullish)\n"
            "- macro_score: float from -1.0 (very bearish) to 1.0 (very bullish)\n"
            "- composite_multiplier: float from 0.5 (reduce trade size) to 1.5 (increase trade size). If mostly neutral, use 1.0.\n"
            "- rationale: a 2-sentence summary of your reasoning.\n\n"
            "Return ONLY valid JSON."
        )

    async def _call_gemini(self, prompt: str) -> dict[str, Any] | None:
        url = f"{self.BASE_URL}/gemini-2.0-flash:generateContent?key={self._api_key}"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 512,
            },
        }
        async with httpx.AsyncClient(timeout=30.0) as http:
            resp = await http.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()

        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])
        text = parts[0].get("text", "") if parts else ""
        
        text = text.strip()
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            text = json_match.group()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            self.logger.warning("Failed to parse Gemini response: %s", text[:200])
            return None
