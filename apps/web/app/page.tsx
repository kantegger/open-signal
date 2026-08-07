"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

interface Card {
  id: string;
  headline: string;
  summary: string;
  trend: "up" | "down" | "neutral";
  probability?: number;
  confidence?: number;
  confidence_label?: string;
  source_label: string;
  section: string;
  tags: string[];
  issued_at: string | null;
}

interface Edition {
  id: string;
  edition_date: string;
  cards: Card[];
}

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function HomePage() {
  const [edition, setEdition] = useState<Edition | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("http://localhost:8000/api/editions/latest")
      .then((r) => (r.ok ? r.json() : null))
      .then(setEdition)
      .catch((e) => setError(e.message));
  }, []);

  if (error)
    return <div className="loading-state">API offline — start uvicorn on :8000</div>;
  if (!edition)
    return <div className="loading-state"><span className="blink">▌</span> Loading Signals...</div>;

  return (
    <div className="card-list">
      {edition.cards.map((card) => (
        <Link key={card.id} href={`/claims/${card.id}`} style={{ textDecoration: "none", color: "inherit" }}>
          <article className="signal-card">
            {/* header: headline + trend badge */}
            <div className="card-header">
              <h2>{card.headline}</h2>
              <span className={`trend-badge trend-${card.trend}`}>
                {card.trend === "up" ? "▲ UP" : card.trend === "down" ? "▼ DOWN" : "– FLAT"}
              </span>
            </div>

            {/* probability line */}
            {card.probability != null && (
              <div className="probability-line">
                <span>{(card.probability * 100).toFixed(1)}%</span>
                <span className={`prob-arrow ${card.trend}`}>
                  {card.trend === "up" ? "→" : card.trend === "down" ? "→" : "→"}
                </span>
              </div>
            )}

            {/* summary */}
            <p className="card-summary">{card.summary}</p>

            {/* meta tags */}
            <div className="card-meta">
              <span className="meta-tag">{card.source_label}</span>
              {card.confidence_label && (
                <span className={`meta-tag confidence-${card.confidence_label?.includes("high") ? "high" : "medium"}`}>
                  {card.confidence_label}
                </span>
              )}
              {card.tags.map((t) => (
                <span key={t} className="meta-tag">{t}</span>
              ))}
            </div>

            {/* footer */}
            <div className="card-footer">
              <span>{card.section}</span>
              <span>{timeAgo(card.issued_at)}</span>
            </div>
          </article>
        </Link>
      ))}

      {edition.cards.length === 0 && (
        <div className="loading-state">No signals today.</div>
      )}
    </div>
  );
}
