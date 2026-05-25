import { useState, useEffect } from 'react';

interface NewsItem {
  title: string;
  source: string;
  url: string;
  publishedAt: string;
  sentiment?: number;
}

interface NewsFeedProps {
  symbol?: string;
  limit?: number;
}

export function NewsFeed({ symbol, limit = 10 }: NewsFeedProps) {
  const [news, setNews] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchNews() {
      setLoading(true);
      try {
        const url = symbol 
          ? `/api/news/${encodeURIComponent(symbol)}?limit=${limit}`
          : `/api/news?limit=${limit}`;
        
        const resp = await fetch(url);
        const json = await resp.json();
        
        if (json.status === 'ok') {
          setNews(json.news || []);
        } else {
          setNews([]);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load news');
        setNews([]);
      }
      setLoading(false);
    }

    fetchNews();
  }, [symbol, limit]);

  const formatTime = (timestamp: string) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const hours = Math.floor(diff / (1000 * 60 * 60));
    
    if (hours < 1) return 'Just now';
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  };

  const getSentimentColor = (sentiment?: number) => {
    if (sentiment === undefined) return 'text-[var(--color-text-secondary)]';
    if (sentiment > 0.3) return 'text-[var(--color-success)]';
    if (sentiment < -0.3) return 'text-[var(--color-danger)]';
    return 'text-[var(--color-warning)]';
  };

  const getSentimentLabel = (sentiment?: number) => {
    if (sentiment === undefined) return '';
    if (sentiment > 0.3) return '🟢 Bullish';
    if (sentiment < -0.3) return '🔴 Bearish';
    return '🟡 Neutral';
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-[var(--color-accent)]"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 text-[var(--color-danger)]">
        Error: {error}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="p-3 border-b border-[var(--color-border)]">
        <h3 className="font-semibold">
          📰 {symbol ? `News for ${symbol}` : 'Market News'}
        </h3>
      </div>
      
      <div className="flex-1 overflow-y-auto">
        {news.length === 0 ? (
          <div className="p-4 text-[var(--color-text-secondary)] text-center">
            No news available
          </div>
        ) : (
          <div className="divide-y divide-[var(--color-border)]">
            {news.map((item, idx) => (
              <a
                key={idx}
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="block p-3 hover:bg-[var(--color-panel)] transition-colors"
              >
                <div className="text-sm line-clamp-2">{item.title}</div>
                <div className="flex items-center gap-2 mt-1 text-xs text-[var(--color-text-secondary)]">
                  <span>{item.source}</span>
                  <span>•</span>
                  <span>{formatTime(item.publishedAt)}</span>
                  {item.sentiment !== undefined && (
                    <>
                      <span>•</span>
                      <span className={getSentimentColor(item.sentiment)}>
                        {getSentimentLabel(item.sentiment)}
                      </span>
                    </>
                  )}
                </div>
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
