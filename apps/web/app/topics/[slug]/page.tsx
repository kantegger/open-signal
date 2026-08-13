import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";
import { JsonLd } from "../../../components/json-ld";
import { DirectionalStatement } from "../../../components/directional-statement";
import { SiteShell } from "../../../components/site-shell";
import { ApiError, type TopicPageData } from "../../../lib/api";
import { collectionDensity } from "../../../lib/collection-density";
import { formatDateTime, formatRelativeTime, humanize, languageAlternates, localePath, type SupportedLocale } from "../../../lib/i18n";
import { getRequestLocale } from "../../../lib/request-locale";
import { fetchTopicServer } from "../../../lib/server-api";
import { absoluteUrl } from "../../../lib/site";
import { excerpt, extractUuid, signalPath, topicPath } from "../../../lib/urls";

export const revalidate = 900;

type Props = { params: Promise<{ slug: string }> };
const getTopic = cache((topicId: string) => fetchTopicServer(topicId));

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const locale = await getRequestLocale();
  const traditional = locale === "zh-Hant";
  const { slug } = await params;
  const topicId = extractUuid(slug);
  if (!topicId) return { title: traditional ? "找不到主題" : "Topic not found", robots: { index: false } };
  try {
    const page = await getTopic(topicId);
    const baseCanonical = topicPath(page.topic.title, topicId);
    const canonical = topicPath(page.topic.title, topicId, locale);
    const description = excerpt(
      traditional
        ? `${page.topic.title}：目前機率、已驗證變化、來源規則與不可變的訊號歷史。`
        : `${page.topic.title} Current probability, verified changes, source rules, and an immutable signal history.`,
    );
    return {
      title: excerpt(page.topic.title, 68),
      description,
      alternates: { canonical, languages: languageAlternates(baseCanonical) },
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
    return { title: traditional ? "找不到主題" : "Topic not found", robots: { index: false } };
  }
}

export default async function TopicPage({ params }: Props) {
  const locale = await getRequestLocale();
  const traditional = locale === "zh-Hant";
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
  const canonical = topicPath(page.topic.title, topicId, locale);
  const tags = page.source_event?.tags ?? page.markets.flatMap((market) => market.tags).slice(0, 8);

  return (
    <>
      <JsonLd
        value={{
          "@context": "https://schema.org",
          "@type": "CollectionPage",
          inLanguage: locale,
          name: page.topic.title,
          description: excerpt(page.topic.resolution_rule_summary),
          url: absoluteUrl(canonical),
          dateModified: page.topic.updated_at,
          mainEntity: {
            "@type": "Dataset",
            name: `${page.topic.title} — probability observations`,
            description: traditional ? "來源機率與已驗證的 Open Signal 變化紀錄。" : "Source probabilities and verified Open Signal change records.",
            temporalCoverage: `${page.topic.created_at}/${page.topic.resolution_deadline_at}`,
            creator: { "@type": "Organization", name: "Open Signal" },
            measurementTechnique: traditional ? "預測市場隱含機率" : "Prediction-market implied probability",
          },
        }}
      />
      <JsonLd
        value={{
          "@context": "https://schema.org",
          "@type": "BreadcrumbList",
          itemListElement: [
            { "@type": "ListItem", position: 1, name: "Open Signal", item: absoluteUrl(localePath("/", locale)) },
            { "@type": "ListItem", position: 2, name: page.topic.title, item: absoluteUrl(canonical) },
          ],
        }}
      />
      <SiteShell active="explore">
        <article className="topic-page">
          <nav className="claim-breadcrumb" aria-label={traditional ? "麵包屑導覽" : "Breadcrumb"}>
            <Link href={localePath("/", locale)}>{traditional ? "即時版面" : "Current"}</Link><span>→</span><span>{traditional ? "預期主題" : "Expectation topic"}</span>
          </nav>

          <header className="topic-header">
            <div>
              <p className="eyebrow">{traditional ? "標準預期" : "Canonical expectation"} · {humanize(page.topic.event_type, locale)}</p>
              <h1>{page.topic.title}</h1>
              {page.source_event?.title && page.source_event.title !== page.topic.title ? <p>{page.source_event.title}</p> : null}
              {tags.length ? <div className="topic-tags">{tags.slice(0, 8).map((tag) => <span key={tag}>{tag}</span>)}</div> : null}
            </div>
            <dl className="topic-facts">
              <div><dt>{traditional ? "狀態" : "Status"}</dt><dd>{humanize(page.topic.status, locale)}</dd></div>
              <div><dt>{traditional ? "結算" : "Resolves"}</dt><dd>{formatDateTime(page.topic.resolution_deadline_at, locale)}</dd></div>
              <div><dt>{traditional ? "市場" : "Markets"}</dt><dd>{page.markets.length}</dd></div>
              <div><dt>{traditional ? "已驗證訊號" : "Verified signals"}</dt><dd>{page.signals.length}</dd></div>
            </dl>
          </header>
          {traditional ? (
            <p className="translation-fallback-notice" role="note">
              命題、來源規則與市場說明目前保留英文原文，以避免未經驗證的翻譯改變結算含義。
            </p>
          ) : null}

          <section className="topic-market-section" aria-labelledby="market-state-title">
            <header className="region-heading"><h2 id="market-state-title">{traditional ? "目前市場狀態" : "Current market state"}</h2><p>{traditional ? "來源機率，不是 Open Signal 預測" : "Source probability, not an Open Signal forecast"}</p></header>
            <div
              className="topic-market-grid"
              data-count={page.markets.length}
              data-density={collectionDensity(page.markets.length, "grid")}
            >
              {page.markets.map((market) => <MarketCard key={market.id} market={market} locale={locale} />)}
            </div>
          </section>

          <section className="topic-rule-section" aria-labelledby="resolution-rule-title">
            <div><p className="eyebrow">{traditional ? "結算契約" : "Resolution contract"}</p><h2 id="resolution-rule-title">{traditional ? "此命題如何結算" : "What settles this proposition"}</h2></div>
            <p>{page.topic.resolution_rule_summary}</p>
            <dl>
              <div><dt>{traditional ? "權威來源" : "Authority"}</dt><dd>{page.topic.resolution_authority || (traditional ? "由來源市場規則定義" : "Defined by the source market rules")}</dd></div>
              <div><dt>{traditional ? "截止時間" : "Deadline"}</dt><dd>{formatDateTime(page.topic.resolution_deadline_at, locale)}</dd></div>
              <div><dt>{traditional ? "標準化器" : "Canonicalizer"}</dt><dd>{page.topic.canonicalization_version}</dd></div>
            </dl>
          </section>

          <section className="topic-signals" aria-labelledby="signal-history-title">
            <header className="region-heading"><h2 id="signal-history-title">{traditional ? "已驗證訊號歷史" : "Verified signal history"}</h2><p>{traditional ? "最新在前" : "Newest first"}</p></header>
            {page.signals.length ? (
              <div
                className="topic-signal-table"
                data-count={page.signals.length}
                data-density={collectionDensity(page.signals.length, "table")}
              >
                {page.signals.map((signal) => (
                  <article key={signal.id}>
                    <time>{formatRelativeTime(signal.issued_at, locale)}</time>
                    <Link href={signalPath(signal.public_statement, signal.id, locale)}>
                      <DirectionalStatement text={signal.public_statement} />
                      <small className="collection-detail collection-detail-balanced">
                        {humanize(signal.claim_type, locale)} · {traditional ? "更新" : "updated"} {formatRelativeTime(signal.updated_at, locale)}
                      </small>
                    </Link>
                    <span>{humanize(signal.confidence_label ?? signal.epistemic_status, locale)}</span>
                    <span>{humanize(signal.status, locale)}</span>
                  </article>
                ))}
              </div>
            ) : <p className="empty-copy">{traditional ? "此主題尚未發布經驗證的變化主張。" : "No verified change Claim has been published for this topic yet."}</p>}
          </section>

          <footer className="topic-method">
            <p className="eyebrow">{traditional ? "方法" : "Method"}</p><p>{page.method.summary}</p>
          </footer>
        </article>
      </SiteShell>
    </>
  );
}

function MarketCard({ market, locale }: { market: TopicPageData["markets"][number]; locale: SupportedLocale }) {
  const traditional = locale === "zh-Hant";
  const current = market.current_probability;
  const delta = market.delta_24h_percentage_points;
  return (
    <article className="topic-market-card">
      <div><p>{market.question}</p>{market.source_url ? <a href={market.source_url} rel="noreferrer" target="_blank">{traditional ? "來源" : "Source"} ↗</a> : null}</div>
      {market.description ? (
        <p className="collection-detail collection-detail-sparse topic-market-description">
          {market.description}
        </p>
      ) : null}
      <div className="topic-probability">
        <strong>{current === null || current === undefined ? "—" : `${Math.round(current * 100)}%`}</strong>
        <span className={delta && delta > 0 ? "trend-up" : delta && delta < 0 ? "trend-down" : "trend-neutral"}>
          {delta === null || delta === undefined
            ? traditional ? "— 等待 24 小時基準" : "— 24h baseline pending"
            : `${delta > 0 ? "↗ +" : delta < 0 ? "↘ " : "→ "}${delta.toFixed(1)}pp · 24h`}
        </span>
      </div>
      <dl>
        <div><dt>{traditional ? "交易量" : "Volume"}</dt><dd>{compactNumber(market.volume, locale)}</dd></div>
        <div><dt>{traditional ? "流動性" : "Liquidity"}</dt><dd>{compactNumber(market.liquidity, locale)}</dd></div>
        <div><dt>{traditional ? "觀測" : "Observed"}</dt><dd>{formatRelativeTime(market.current_observed_at, locale)}</dd></div>
      </dl>
    </article>
  );
}

function compactNumber(value: number | null | undefined, locale: SupportedLocale): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 1 }).format(value);
}
