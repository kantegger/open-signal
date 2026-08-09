import type { Metadata } from "next";
import Link from "next/link";
import { JsonLd } from "../../components/json-ld";
import { DirectionalStatement } from "../../components/directional-statement";
import { SiteShell } from "../../components/site-shell";
import type { SeoIndexData } from "../../lib/api";
import { formatDateTime, formatRelativeTime, humanize } from "../../lib/i18n";
import { fetchSeoIndexServer } from "../../lib/server-api";
import { absoluteUrl } from "../../lib/site";
import { signalPath, topicPath } from "../../lib/urls";

export const revalidate = 900;
export const metadata: Metadata = {
  title: "Explore Signals and Topics",
  description:
    "Browse active public Topics and verified Open Signal records across expectations, rules, and research.",
  alternates: { canonical: "/explore" },
  openGraph: {
    title: "Explore Signals and Topics · Open Signal",
    description: "A source-linked discovery index of active Topics and verified Signals.",
    url: "/explore",
  },
};

const SIGNALS_PER_PAGE = 60;
const TOPICS_PER_PAGE = 24;

type Props = { searchParams: Promise<{ page?: string }> };
type TopicIndexItem = SeoIndexData["topics"][number];

export default async function ExplorePage({ searchParams }: Props) {
  const { page: rawPage } = await searchParams;
  const page = parsePage(rawPage);
  let index;
  try {
    index = await fetchSeoIndexServer();
  } catch {
    return (
      <SiteShell active="explore" systemState="unavailable">
        <div className="claim-route-state">
          <p className="eyebrow">Discovery index unavailable</p>
          <h1>Signals and Topics could not be loaded.</h1>
          <p>The permanent records are unchanged. Try this directory again after the publication service recovers.</p>
          <Link href="/">Return to Current</Link>
        </div>
      </SiteShell>
    );
  }

  const topicStart = (page - 1) * TOPICS_PER_PAGE;
  const signalStart = (page - 1) * SIGNALS_PER_PAGE;
  const topics = index.topics.slice(topicStart, topicStart + TOPICS_PER_PAGE);
  const signals = index.claims.slice(signalStart, signalStart + SIGNALS_PER_PAGE);
  const pageCount = Math.max(
    1,
    Math.ceil(index.topics.length / TOPICS_PER_PAGE),
    Math.ceil(index.claims.length / SIGNALS_PER_PAGE),
  );

  return (
    <>
      <JsonLd
        value={{
          "@context": "https://schema.org",
          "@type": "CollectionPage",
          name: "Explore Open Signal",
          url: absoluteUrl("/explore"),
          mainEntity: {
            "@type": "ItemList",
            numberOfItems: topics.length + signals.length,
            itemListElement: [
              ...topics.map((topic, indexPosition) => ({
                "@type": "ListItem",
                position: indexPosition + 1,
                name: topic.title,
                url: absoluteUrl(topicPath(topic.title, topic.id)),
              })),
              ...signals.map((signal, indexPosition) => ({
                "@type": "ListItem",
                position: topics.length + indexPosition + 1,
                name: signal.title,
                url: absoluteUrl(signalPath(signal.title, signal.id)),
              })),
            ],
          },
        }}
      />
      <SiteShell active="explore">
        <article className="directory-page">
          <header className="directory-header">
            <div>
              <p className="eyebrow">Discovery, not a second front page</p>
              <h1>Explore Signals and Topics</h1>
            </div>
            <p>
              Current is the editorial snapshot. Explore is the durable index: long-lived public
              questions and every recent verified Signal that supports them.
            </p>
          </header>

          <dl className="directory-metrics" aria-label="Discovery index coverage">
            <div><dt>Active topics</dt><dd>{index.topics.length}</dd></div>
            <div><dt>Verified Signals</dt><dd>{index.claims.length}</dd></div>
            <div><dt>Page</dt><dd>{page} / {pageCount}</dd></div>
            <div><dt>Refresh model</dt><dd>Event-driven · hourly sweep</dd></div>
          </dl>

          <section className="directory-section topic-directory" aria-labelledby="active-topics-title">
            <header className="directory-section-heading">
              <div><p className="eyebrow">Canonical expectations</p><h2 id="active-topics-title">Active Topics</h2></div>
              <p>{topics.length} shown · grouped across source markets</p>
            </header>
            {topics.length ? (
              <div className="topic-directory-grid">
                {topics.map((topic) => (
                  <article key={topic.id}>
                    <p className="eyebrow">{humanize(topic.event_type)}</p>
                    <h3><Link href={topicPath(topic.title, topic.id)}>{topic.title}</Link></h3>
                    <TopicSignal topic={topic} />
                    <dl>
                      <div><dt>Markets</dt><dd>{topic.source_market_count}</dd></div>
                      <div><dt>Resolves</dt><dd>{formatDateTime(topic.resolution_deadline_at)}</dd></div>
                      <div><dt>Updated</dt><dd>{formatRelativeTime(topic.updated_at)}</dd></div>
                    </dl>
                  </article>
                ))}
              </div>
            ) : <p className="empty-copy">No active Topics appear on this page.</p>}
          </section>

          <section className="directory-section signal-directory" aria-labelledby="signal-index-title">
            <header className="directory-section-heading">
              <div><p className="eyebrow">Permanent public records</p><h2 id="signal-index-title">Recent Signals</h2></div>
              <p>{signals.length} shown · newest assessments first</p>
            </header>
            {signals.length ? (
              <div className="signal-directory-table" role="table" aria-label="Recent verified Signals">
                <div className="signal-directory-row signal-directory-head" role="row">
                  <span role="columnheader">Desk</span><span role="columnheader">Signal</span>
                  <span role="columnheader">Confidence</span><span role="columnheader">Valid until</span>
                  <span role="columnheader">Updated</span>
                </div>
                {signals.map((signal) => (
                  <div className="signal-directory-row" role="row" key={signal.id}>
                    <span role="cell">{deskName(signal.desk_id)}</span>
                    <span role="cell"><Link href={signalPath(signal.title, signal.id)}><DirectionalStatement text={signal.title} /></Link></span>
                    <span role="cell">{humanize(signal.confidence_label ?? signal.epistemic_status)}</span>
                    <time role="cell">{signal.valid_until ? formatDateTime(signal.valid_until) : "Open"}</time>
                    <time role="cell">{formatRelativeTime(signal.updated_at)}</time>
                  </div>
                ))}
              </div>
            ) : <p className="empty-copy">No verified Signals appear on this page.</p>}
          </section>

          {pageCount > 1 ? (
            <nav aria-label="Explore pagination" className="directory-pagination">
              {page > 1 ? <Link href={page === 2 ? "/explore" : `/explore?page=${page - 1}`}>← Newer</Link> : <span />}
              <span>Page {page} of {pageCount}</span>
              {page < pageCount ? <Link href={`/explore?page=${page + 1}`}>Older →</Link> : <span />}
            </nav>
          ) : null}
        </article>
      </SiteShell>
    </>
  );
}

function TopicSignal({ topic }: { topic: TopicIndexItem }) {
  const hasProbability = topic.current_probability != null;
  const observedAt = topic.current_observed_at ?? topic.updated_at;
  const delta = topic.delta_24h_percentage_points;
  const trendClass = topicTrendClass(delta);
  return (
    <div
      aria-label={hasProbability
        ? `Latest source probability ${formatTopicProbability(topic.current_probability)}${delta == null ? "" : `, ${formatTopicDelta(delta)} over 24 hours`}`
        : `Resolution ${formatRelativeTime(topic.resolution_deadline_at)}; source probability unavailable`}
      className="topic-directory-signal"
    >
      <span>{hasProbability ? "Latest source probability" : "Resolution window"}</span>
      <strong>{hasProbability ? formatTopicProbability(topic.current_probability) : formatRelativeTime(topic.resolution_deadline_at)}</strong>
      <div>
        <b className={trendClass}>
          {hasProbability && delta != null
            ? `${topicTrendGlyph(delta)} ${formatTopicDelta(delta)} · 24h`
            : "— no 24h baseline"}
        </b>
        <time dateTime={hasProbability ? observedAt : topic.resolution_deadline_at}>
          {hasProbability ? `observed ${formatRelativeTime(observedAt)}` : formatDateTime(topic.resolution_deadline_at)}
        </time>
      </div>
    </div>
  );
}

function parsePage(value: string | undefined): number {
  const parsed = Number.parseInt(value ?? "1", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}

function formatTopicProbability(value: number | null | undefined): string {
  if (value == null) return "—";
  const percentage = Math.abs(value) <= 1 ? value * 100 : value;
  return `${Math.round(percentage * 10) / 10}%`;
}

function formatTopicDelta(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  return `${rounded > 0 ? "+" : ""}${rounded}pp`;
}

function topicTrendClass(value: number | null | undefined): string {
  if (value == null || Math.abs(value) < 0.05) return "trend-neutral";
  return value > 0 ? "trend-up" : "trend-down";
}

function topicTrendGlyph(value: number): string {
  if (Math.abs(value) < 0.05) return "→";
  return value > 0 ? "↗" : "↘";
}

function deskName(deskId: string): string {
  if (deskId.includes("expectation")) return "Expectations";
  if (deskId.includes("rule")) return "Rules";
  if (deskId.includes("research")) return "Research";
  return humanize(deskId);
}
