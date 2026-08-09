import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";
import { JsonLd } from "../../../components/json-ld";
import { DirectionalStatement } from "../../../components/directional-statement";
import { SiteShell } from "../../../components/site-shell";
import { ApiError, type TopicPageData } from "../../../lib/api";
import { formatDateTime, formatRelativeTime, humanize } from "../../../lib/i18n";
import { fetchTopicServer } from "../../../lib/server-api";
import { absoluteUrl } from "../../../lib/site";
import { excerpt, extractUuid, signalPath, topicPath } from "../../../lib/urls";

export const revalidate = 900;

type Props = { params: Promise<{ slug: string }> };
const getTopic = cache((topicId: string) => fetchTopicServer(topicId));

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const topicId = extractUuid(slug);
  if (!topicId) return { title: "Topic not found", robots: { index: false } };
  try {
    const page = await getTopic(topicId);
    const canonical = topicPath(page.topic.title, topicId);
    const description = excerpt(
      `${page.topic.title} Current probability, verified changes, source rules, and an immutable signal history.`,
    );
    return {
      title: excerpt(page.topic.title, 68),
      description,
      alternates: { canonical },
      openGraph: {
        type: "website",
        siteName: "Open Signal",
        title: page.topic.title,
        description,
        url: canonical,
      },
      twitter: { card: "summary_large_image", title: page.topic.title, description },
    };
  } catch {
    return { title: "Topic not found", robots: { index: false } };
  }
}

export default async function TopicPage({ params }: Props) {
  const { slug } = await params;
  const topicId = extractUuid(slug);
  if (!topicId) notFound();
  let page: TopicPageData;
  try {
    page = await getTopic(topicId);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
  const canonical = topicPath(page.topic.title, topicId);
  const tags = page.source_event?.tags ?? page.markets.flatMap((market) => market.tags).slice(0, 8);

  return (
    <>
      <JsonLd
        value={{
          "@context": "https://schema.org",
          "@type": "CollectionPage",
          name: page.topic.title,
          description: excerpt(page.topic.resolution_rule_summary),
          url: absoluteUrl(canonical),
          dateModified: page.topic.updated_at,
          mainEntity: {
            "@type": "Dataset",
            name: `${page.topic.title} — probability observations`,
            description: "Source probabilities and verified Open Signal change records.",
            temporalCoverage: `${page.topic.created_at}/${page.topic.resolution_deadline_at}`,
            creator: { "@type": "Organization", name: "Open Signal" },
            measurementTechnique: "Prediction-market implied probability",
          },
        }}
      />
      <JsonLd
        value={{
          "@context": "https://schema.org",
          "@type": "BreadcrumbList",
          itemListElement: [
            { "@type": "ListItem", position: 1, name: "Open Signal", item: absoluteUrl("/") },
            { "@type": "ListItem", position: 2, name: page.topic.title, item: absoluteUrl(canonical) },
          ],
        }}
      />
      <SiteShell active="explore">
        <article className="topic-page">
          <nav className="claim-breadcrumb" aria-label="Breadcrumb">
            <Link href="/">Current</Link><span>→</span><span>Expectation topic</span>
          </nav>

          <header className="topic-header">
            <div>
              <p className="eyebrow">Canonical expectation · {humanize(page.topic.event_type)}</p>
              <h1>{page.topic.title}</h1>
              {page.source_event?.title && page.source_event.title !== page.topic.title ? <p>{page.source_event.title}</p> : null}
              {tags.length ? <div className="topic-tags">{tags.slice(0, 8).map((tag) => <span key={tag}>{tag}</span>)}</div> : null}
            </div>
            <dl className="topic-facts">
              <div><dt>Status</dt><dd>{humanize(page.topic.status)}</dd></div>
              <div><dt>Resolves</dt><dd>{formatDateTime(page.topic.resolution_deadline_at)}</dd></div>
              <div><dt>Markets</dt><dd>{page.markets.length}</dd></div>
              <div><dt>Verified signals</dt><dd>{page.signals.length}</dd></div>
            </dl>
          </header>

          <section className="topic-market-section" aria-labelledby="market-state-title">
            <header className="region-heading"><h2 id="market-state-title">Current market state</h2><p>Source probability, not an Open Signal forecast</p></header>
            <div className="topic-market-grid">
              {page.markets.map((market) => <MarketCard key={market.id} market={market} />)}
            </div>
          </section>

          <section className="topic-rule-section" aria-labelledby="resolution-rule-title">
            <div><p className="eyebrow">Resolution contract</p><h2 id="resolution-rule-title">What settles this proposition</h2></div>
            <p>{page.topic.resolution_rule_summary}</p>
            <dl>
              <div><dt>Authority</dt><dd>{page.topic.resolution_authority || "Defined by the source market rules"}</dd></div>
              <div><dt>Deadline</dt><dd>{formatDateTime(page.topic.resolution_deadline_at)}</dd></div>
              <div><dt>Canonicalizer</dt><dd>{page.topic.canonicalization_version}</dd></div>
            </dl>
          </section>

          <section className="topic-signals" aria-labelledby="signal-history-title">
            <header className="region-heading"><h2 id="signal-history-title">Verified signal history</h2><p>Newest first</p></header>
            {page.signals.length ? (
              <div className="topic-signal-table">
                {page.signals.map((signal) => (
                  <article key={signal.id}>
                    <time>{formatRelativeTime(signal.issued_at)}</time>
                    <Link href={signalPath(signal.public_statement, signal.id)}><DirectionalStatement text={signal.public_statement} /></Link>
                    <span>{humanize(signal.confidence_label ?? signal.epistemic_status)}</span>
                    <span>{humanize(signal.status)}</span>
                  </article>
                ))}
              </div>
            ) : <p className="empty-copy">No verified change Claim has been published for this topic yet.</p>}
          </section>

          <footer className="topic-method">
            <p className="eyebrow">Method</p><p>{page.method.summary}</p>
          </footer>
        </article>
      </SiteShell>
    </>
  );
}

function MarketCard({ market }: { market: TopicPageData["markets"][number] }) {
  const current = market.current_probability;
  const delta = market.delta_24h_percentage_points;
  return (
    <article className="topic-market-card">
      <div><p>{market.question}</p>{market.source_url ? <a href={market.source_url} rel="noreferrer" target="_blank">Source ↗</a> : null}</div>
      <div className="topic-probability">
        <strong>{current === null || current === undefined ? "—" : `${Math.round(current * 100)}%`}</strong>
        <span className={delta && delta > 0 ? "trend-up" : delta && delta < 0 ? "trend-down" : "trend-neutral"}>
          {delta === null || delta === undefined
            ? "— 24h baseline pending"
            : `${delta > 0 ? "↗ +" : delta < 0 ? "↘ " : "→ "}${delta.toFixed(1)}pp · 24h`}
        </span>
      </div>
      <dl>
        <div><dt>Volume</dt><dd>{compactNumber(market.volume)}</dd></div>
        <div><dt>Liquidity</dt><dd>{compactNumber(market.liquidity)}</dd></div>
        <div><dt>Observed</dt><dd>{formatRelativeTime(market.current_observed_at)}</dd></div>
      </dl>
    </article>
  );
}

function compactNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}
