import type { Metadata } from "next";
import Link from "next/link";
import { DirectionalStatement } from "../../components/directional-statement";
import { JsonLd } from "../../components/json-ld";
import { SiteShell } from "../../components/site-shell";
import type { ExploreData, ExploreEventGroup } from "../../lib/api";
import { collectionDensity } from "../../lib/collection-density";
import {
  formatDateTime,
  formatRelativeTime,
  humanize,
  languageAlternates,
  localePath,
  type SupportedLocale,
} from "../../lib/i18n";
import { getRequestLocale } from "../../lib/request-locale";
import { fetchExploreServer } from "../../lib/server-api";
import { absoluteUrl } from "../../lib/site";
import { signalPath, topicPath } from "../../lib/urls";

export const revalidate = 900;
export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  const traditional = locale === "zh-Hant";
  const canonical = localePath("/explore", locale);
  const description = traditional
    ? "依事件重要性探索公共訊號、代表性結果與已驗證的 Open Signal 永久紀錄。"
    : "Explore event-ranked public signals, representative outcomes, and verified Open Signal records.";
  return {
    title: traditional ? "探索訊號與主題" : "Explore Signals and Topics",
    description,
    alternates: { canonical, languages: languageAlternates("/explore") },
    openGraph: {
      title: traditional ? "探索訊號與主題 · Open Signal" : "Explore Signals and Topics · Open Signal",
      description: traditional
        ? "以事件為單位，探索具實質意義的公共訊號與永久紀錄。"
        : "An event-aware discovery view of material public signals and durable records.",
      url: canonical,
    },
  };
}

type Props = {
  searchParams: Promise<{
    topic_page?: string;
    signal_page?: string;
    as_of?: string;
  }>;
};

export default async function ExplorePage({ searchParams }: Props) {
  const locale = await getRequestLocale();
  const traditional = locale === "zh-Hant";
  const params = await searchParams;
  let data: ExploreData;
  try {
    data = await fetchExploreServer({
      topicPage: parsePage(params.topic_page),
      signalPage: parsePage(params.signal_page),
      asOf: params.as_of,
      locale,
    });
  } catch {
    return (
      <SiteShell active="explore" systemState="unavailable">
        <div className="claim-route-state">
          <p className="eyebrow">{traditional ? "探索頁面暫時無法使用" : "Discovery view unavailable"}</p>
          <h1>{traditional ? "目前無法排列訊號與主題。" : "Signals and Topics could not be ranked."}</h1>
          <p>
            {traditional
              ? "永久紀錄沒有變動。請在出版服務恢復後重試此頁面。"
              : "Permanent records are unchanged. Try this view again after the publication service recovers."}
          </p>
          <Link href={localePath("/", locale)}>{traditional ? "返回即時版面" : "Return to Current"}</Link>
        </div>
      </SiteShell>
    );
  }

  const topics = data.topics.items;
  const signals = data.signals.items;
  return (
    <>
      <JsonLd
        value={{
          "@context": "https://schema.org",
          "@type": "CollectionPage",
          name: traditional ? "探索 Open Signal" : "Explore Open Signal",
          inLanguage: locale,
          url: absoluteUrl(localePath("/explore", locale)),
          mainEntity: {
            "@type": "ItemList",
            numberOfItems:
              topics.reduce((total, group) => total + group.members.length, 0) +
              signals.length,
            itemListElement: [
              ...topics.flatMap((group) =>
                group.members.map((member) => ({
                  "@type": "ListItem",
                  name: member.title,
                  url: absoluteUrl(topicPath(member.title, member.topic_id, locale)),
                })),
              ),
              ...signals.map((signal) => ({
                "@type": "ListItem",
                name: signal.title,
                url: absoluteUrl(signalPath(signal.title, signal.id, locale)),
              })),
            ].map((item, index) => ({ ...item, position: index + 1 })),
          },
        }}
      />
      <SiteShell active="explore">
        <article className="directory-page">
          <header className="directory-header">
            <div>
              <p className="eyebrow">{traditional ? "依訊號重要性排序" : "Discovery, ranked by signal"}</p>
              <h1>{traditional ? "探索訊號與主題" : "Explore Signals and Topics"}</h1>
            </div>
            <p>
              {traditional
                ? "每個市場仍保留為命題層級的公開紀錄；探索頁將它們按來源事件分組，只呈現領先者、重大變動者，或足以解釋事件為何此刻重要的可信挑戰者。"
                : "Markets remain proposition-level public records. Explore groups them into source events and surfaces only the leader, material mover, or credible challenger that explains why the event matters now."}
            </p>
          </header>
          {traditional ? (
            <p className="translation-fallback-notice" role="note">
              事件與市場標題目前保留來源的英文原文；介面、方法說明與時間格式已使用繁體中文。
            </p>
          ) : null}

          <dl className="directory-metrics" aria-label={traditional ? "探索選取涵蓋範圍" : "Explore selection coverage"}>
            <div>
              <dt>{traditional ? "符合資格的命題" : "Eligible propositions"}</dt>
              <dd>{data.topics.public_inventory_count}</dd>
            </div>
            <div>
              <dt>{traditional ? "入選事件" : "Selected events"}</dt>
              <dd>{data.topics.selected_group_count}</dd>
            </div>
            <div>
              <dt>{traditional ? "近期訊號主體" : "Recent Signal subjects"}</dt>
              <dd>{data.signals.current_subject_count}</dd>
            </div>
            <div>
              <dt>{traditional ? "排序截至" : "Ranked as of"}</dt>
              <dd>{formatDateTime(data.ranking_as_of, locale)}</dd>
            </div>
          </dl>

          <section
            className="directory-section event-directory"
            aria-labelledby="selected-events-title"
          >
            <header className="directory-section-heading">
              <div>
                <p className="eyebrow">{traditional ? "以事件為單位的預期" : "Event-aware expectations"}</p>
                <h2 id="selected-events-title">{traditional ? "精選事件訊號" : "Selected Event Signals"}</h2>
              </div>
              <p>
                {traditional
                  ? `顯示 ${topics.length} 組 · 已收起 ${data.topics.suppressed_proposition_count} 個較低價值命題`
                  : `${topics.length} shown · ${data.topics.suppressed_proposition_count} lower-value propositions folded away`}
              </p>
            </header>
            {topics.length ? (
              <div
                className="event-directory-grid"
                data-count={topics.length}
                data-density={collectionDensity(topics.length, "grid")}
              >
                {topics.map((group) => (
                  <EventGroupCard group={group} key={group.key} locale={locale} />
                ))}
              </div>
            ) : (
              <p className="empty-copy">
                {traditional ? "目前沒有事件通過公開選取門檻。" : "No event currently clears the public selection threshold."}
              </p>
            )}
            <ExplorePagination
              ariaLabel={traditional ? "精選事件分頁" : "Selected event pagination"}
              current={data.topics.page}
              pageCount={data.topics.page_count}
              previousLabel={traditional ? "較新事件" : "Newer events"}
              nextLabel={traditional ? "更多事件" : "More events"}
              previousHref={exploreHref(data, {
                topicPage: data.topics.page - 1,
              }, locale)}
              nextHref={exploreHref(data, {
                topicPage: data.topics.page + 1,
              }, locale)}
              locale={locale}
            />
          </section>

          <section
            className="directory-section signal-directory"
            aria-labelledby="signal-index-title"
          >
            <header className="directory-section-heading">
              <div>
                <p className="eyebrow">{traditional ? "每個主體的目前紀錄" : "Current record per subject"}</p>
                <h2 id="signal-index-title">{traditional ? "近期訊號" : "Recent Signals"}</h2>
              </div>
              <p>
                {traditional ? `顯示 ${signals.length} 筆 · 較早快照仍保留在公開帳本` : `${signals.length} shown · older snapshots remain in the public ledger`}
              </p>
            </header>
            {signals.length ? (
              <div
                className="signal-directory-table"
                role="table"
                aria-label={traditional ? "近期已驗證訊號" : "Recent verified Signals"}
                data-count={signals.length}
                data-density={collectionDensity(signals.length, "table")}
              >
                <div className="signal-directory-row signal-directory-head" role="row">
                  <span role="columnheader">{traditional ? "編輯台" : "Desk"}</span>
                  <span role="columnheader">{traditional ? "訊號" : "Signal"}</span>
                  <span role="columnheader">{traditional ? "事件／主體" : "Event / subject"}</span>
                  <span role="columnheader">{traditional ? "有效至" : "Valid until"}</span>
                  <span role="columnheader">{traditional ? "更新" : "Updated"}</span>
                </div>
                {signals.map((signal) => (
                  <div className="signal-directory-row" role="row" key={signal.id}>
                    <span role="cell">{deskName(signal.desk_id, locale)}</span>
                    <span role="cell">
                      <Link href={signalPath(signal.title, signal.id, locale)}>
                        <DirectionalStatement text={signal.title} />
                      </Link>
                      <small>
                        {humanize(signal.claim_type, locale)} · {humanize(signal.status, locale)}
                      </small>
                    </span>
                    <span role="cell">
                      {signal.topic_id && signal.event_title ? (
                        <Link href={topicPath(signal.event_title, signal.topic_id, locale)}>
                          {signal.event_title}
                        </Link>
                      ) : (
                        humanize(signal.section_id, locale)
                      )}
                    </span>
                    <time role="cell">
                      {signal.valid_until ? formatDateTime(signal.valid_until, locale) : traditional ? "仍有效" : "Open"}
                    </time>
                    <time role="cell">{formatRelativeTime(signal.updated_at, locale)}</time>
                  </div>
                ))}
              </div>
            ) : (
              <p className="empty-copy">{traditional ? "此頁目前沒有已驗證訊號。" : "No current verified Signals appear on this page."}</p>
            )}
            <ExplorePagination
              ariaLabel={traditional ? "近期訊號分頁" : "Recent Signal pagination"}
              current={data.signals.page}
              pageCount={data.signals.page_count}
              previousLabel={traditional ? "較新訊號" : "Newer Signals"}
              nextLabel={traditional ? "更多訊號" : "More Signals"}
              previousHref={exploreHref(data, {
                signalPage: data.signals.page - 1,
              }, locale)}
              nextHref={exploreHref(data, {
                signalPage: data.signals.page + 1,
              }, locale)}
              locale={locale}
            />
          </section>
        </article>
      </SiteShell>
    </>
  );
}

function EventGroupCard({ group, locale }: { group: ExploreEventGroup; locale: SupportedLocale }) {
  const traditional = locale === "zh-Hant";
  return (
    <article className="event-signal-card">
      <header>
        <p className="eyebrow">
          <span>{humanize(group.event_type, locale)}</span>
          <span>{humanize(group.selection_reason, locale)}</span>
        </p>
        <h3>{group.title}</h3>
        <p className="event-signal-summary">
          {group.is_exclusive_slate
            ? traditional ? "互斥結果組" : "Mutually exclusive outcome slate"
            : traditional ? "相關來源市場" : "Related source markets"}
          {traditional
            ? ` · 24 小時交易量 ${formatCompactNumber(group.volume_24h, locale)}`
            : ` · ${formatCompactNumber(group.volume_24h, locale)} traded in 24h`}
        </p>
      </header>
      <ol className="event-member-list">
        {group.members.map((member) => {
          const delta = member.delta_24h_percentage_points;
          const probability = normalizeProbability(member.current_probability);
          return (
            <li key={member.topic_id}>
              <div>
                <small>{humanize(member.selection_reason, locale)}</small>
                <Link href={topicPath(member.title, member.topic_id, locale)}>
                  {member.option_label || member.title}
                </Link>
                {member.option_label ? <p>{member.title}</p> : null}
              </div>
              <div
                aria-label={`${member.option_label || member.title}: ${formatTopicProbability(member.current_probability)}`}
                className="event-probability-bar"
              >
                <i aria-hidden="true" style={{ inlineSize: `${Math.max(1.5, probability)}%` }} />
                <strong>{formatTopicProbability(member.current_probability)}</strong>
              </div>
              <b className={topicTrendClass(delta)}>
                {delta == null
                  ? "—"
                  : `${topicTrendGlyph(delta)} ${formatTopicDelta(delta)}`}
              </b>
            </li>
          );
        })}
      </ol>
      <footer>
        <div>
          <span>
            {traditional ? "觀測於" : "Observed"} {formatRelativeTime(group.latest_observed_at, locale)} · {traditional ? "結算" : "resolves"}{" "}
            {formatDateTime(group.resolution_deadline_at, locale)}
          </span>
          {group.suppressed_member_count > 0 ? (
            <strong>+{group.suppressed_member_count} {traditional ? "個來源結果已收進此事件" : "source outcomes folded into this event"}</strong>
          ) : (
            <strong>{traditional ? "完整事件檢視" : "Complete event view"}</strong>
          )}
        </div>
        {group.source_url ? (
          <a href={group.source_url} rel="noreferrer" target="_blank">
            {group.source_label} ↗
          </a>
        ) : (
          <span>{group.source_label}</span>
        )}
      </footer>
    </article>
  );
}

function ExplorePagination({
  ariaLabel,
  current,
  pageCount,
  previousLabel,
  nextLabel,
  previousHref,
  nextHref,
  locale,
}: {
  ariaLabel: string;
  current: number;
  pageCount: number;
  previousLabel: string;
  nextLabel: string;
  previousHref: string;
  nextHref: string;
  locale: SupportedLocale;
}) {
  if (pageCount <= 1) return null;
  return (
    <nav aria-label={ariaLabel} className="directory-pagination">
      {current > 1 ? <Link href={previousHref}>← {previousLabel}</Link> : <span />}
      <span>
        {locale === "zh-Hant" ? `第 ${current} 頁，共 ${pageCount} 頁` : `Page ${current} of ${pageCount}`}
      </span>
      {current < pageCount ? <Link href={nextHref}>{nextLabel} →</Link> : <span />}
    </nav>
  );
}

function exploreHref(
  data: ExploreData,
  override: { topicPage?: number; signalPage?: number },
  locale: SupportedLocale,
): string {
  const query = new URLSearchParams({ as_of: data.ranking_as_of });
  const topicPage = override.topicPage ?? data.topics.page;
  const signalPage = override.signalPage ?? data.signals.page;
  if (topicPage > 1) query.set("topic_page", String(topicPage));
  if (signalPage > 1) query.set("signal_page", String(signalPage));
  return localePath(`/explore?${query.toString()}`, locale);
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

function normalizeProbability(value: number | null | undefined): number {
  if (value == null || !Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, Math.abs(value) <= 1 ? value * 100 : value));
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

function formatCompactNumber(value: number, locale: SupportedLocale): string {
  return new Intl.NumberFormat(locale, {
    notation: "compact",
    maximumFractionDigits: 1,
    style: "currency",
    currency: "USD",
  }).format(value);
}

function deskName(deskId: string, locale: SupportedLocale): string {
  if (deskId.includes("expectation")) return locale === "zh-Hant" ? "預期變化" : "Expectations";
  if (deskId.includes("rule")) return locale === "zh-Hant" ? "規則變化" : "Rules";
  if (deskId.includes("research")) return locale === "zh-Hant" ? "研究動向" : "Research";
  return humanize(deskId, locale);
}
