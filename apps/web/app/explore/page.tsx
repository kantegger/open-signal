import type { Metadata } from "next";
import Link from "next/link";
import { DirectionalStatement } from "../../components/directional-statement";
import { JsonLd } from "../../components/json-ld";
import { SiteShell } from "../../components/site-shell";
import type { ExploreData, ExploreEventGroup } from "../../lib/api";
import { collectionDensity } from "../../lib/collection-density";
import { formatDateTime, formatRelativeTime, humanize } from "../../lib/i18n";
import { fetchExploreServer } from "../../lib/server-api";
import { absoluteUrl } from "../../lib/site";
import { signalPath, topicPath } from "../../lib/urls";

export const revalidate = 900;
export const metadata: Metadata = {
  title: "Explore Signals and Topics",
  description:
    "Explore event-ranked public signals, representative outcomes, and verified Open Signal records.",
  alternates: { canonical: "/explore" },
  openGraph: {
    title: "Explore Signals and Topics · Open Signal",
    description:
      "An event-aware discovery view of material public signals and durable records.",
    url: "/explore",
  },
};

type Props = {
  searchParams: Promise<{
    topic_page?: string;
    signal_page?: string;
    as_of?: string;
  }>;
};

export default async function ExplorePage({ searchParams }: Props) {
  const params = await searchParams;
  let data: ExploreData;
  try {
    data = await fetchExploreServer({
      topicPage: parsePage(params.topic_page),
      signalPage: parsePage(params.signal_page),
      asOf: params.as_of,
    });
  } catch {
    return (
      <SiteShell active="explore" systemState="unavailable">
        <div className="claim-route-state">
          <p className="eyebrow">Discovery view unavailable</p>
          <h1>Signals and Topics could not be ranked.</h1>
          <p>
            Permanent records are unchanged. Try this view again after the publication
            service recovers.
          </p>
          <Link href="/">Return to Current</Link>
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
          name: "Explore Open Signal",
          url: absoluteUrl("/explore"),
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
                  url: absoluteUrl(topicPath(member.title, member.topic_id)),
                })),
              ),
              ...signals.map((signal) => ({
                "@type": "ListItem",
                name: signal.title,
                url: absoluteUrl(signalPath(signal.title, signal.id)),
              })),
            ].map((item, index) => ({ ...item, position: index + 1 })),
          },
        }}
      />
      <SiteShell active="explore">
        <article className="directory-page">
          <header className="directory-header">
            <div>
              <p className="eyebrow">Discovery, ranked by signal</p>
              <h1>Explore Signals and Topics</h1>
            </div>
            <p>
              Markets remain proposition-level public records. Explore groups them into
              source events and surfaces only the leader, material mover, or credible
              challenger that explains why the event matters now.
            </p>
          </header>

          <dl className="directory-metrics" aria-label="Explore selection coverage">
            <div>
              <dt>Eligible propositions</dt>
              <dd>{data.topics.public_inventory_count}</dd>
            </div>
            <div>
              <dt>Selected events</dt>
              <dd>{data.topics.selected_group_count}</dd>
            </div>
            <div>
              <dt>Recent Signal subjects</dt>
              <dd>{data.signals.current_subject_count}</dd>
            </div>
            <div>
              <dt>Ranked as of</dt>
              <dd>{formatDateTime(data.ranking_as_of)}</dd>
            </div>
          </dl>

          <section
            className="directory-section event-directory"
            aria-labelledby="selected-events-title"
          >
            <header className="directory-section-heading">
              <div>
                <p className="eyebrow">Event-aware expectations</p>
                <h2 id="selected-events-title">Selected Event Signals</h2>
              </div>
              <p>
                {topics.length} shown · {data.topics.suppressed_proposition_count} lower-value
                propositions folded away
              </p>
            </header>
            {topics.length ? (
              <div
                className="event-directory-grid"
                data-count={topics.length}
                data-density={collectionDensity(topics.length, "grid")}
              >
                {topics.map((group) => (
                  <EventGroupCard group={group} key={group.key} />
                ))}
              </div>
            ) : (
              <p className="empty-copy">
                No event currently clears the public selection threshold.
              </p>
            )}
            <ExplorePagination
              ariaLabel="Selected event pagination"
              current={data.topics.page}
              pageCount={data.topics.page_count}
              previousLabel="Newer events"
              nextLabel="More events"
              previousHref={exploreHref(data, {
                topicPage: data.topics.page - 1,
              })}
              nextHref={exploreHref(data, {
                topicPage: data.topics.page + 1,
              })}
            />
          </section>

          <section
            className="directory-section signal-directory"
            aria-labelledby="signal-index-title"
          >
            <header className="directory-section-heading">
              <div>
                <p className="eyebrow">Current record per subject</p>
                <h2 id="signal-index-title">Recent Signals</h2>
              </div>
              <p>
                {signals.length} shown · older snapshots remain in the public ledger
              </p>
            </header>
            {signals.length ? (
              <div
                className="signal-directory-table"
                role="table"
                aria-label="Recent verified Signals"
                data-count={signals.length}
                data-density={collectionDensity(signals.length, "table")}
              >
                <div className="signal-directory-row signal-directory-head" role="row">
                  <span role="columnheader">Desk</span>
                  <span role="columnheader">Signal</span>
                  <span role="columnheader">Event / subject</span>
                  <span role="columnheader">Valid until</span>
                  <span role="columnheader">Updated</span>
                </div>
                {signals.map((signal) => (
                  <div className="signal-directory-row" role="row" key={signal.id}>
                    <span role="cell">{deskName(signal.desk_id)}</span>
                    <span role="cell">
                      <Link href={signalPath(signal.title, signal.id)}>
                        <DirectionalStatement text={signal.title} />
                      </Link>
                      <small>
                        {humanize(signal.claim_type)} · {humanize(signal.status)}
                      </small>
                    </span>
                    <span role="cell">
                      {signal.topic_id && signal.event_title ? (
                        <Link href={topicPath(signal.event_title, signal.topic_id)}>
                          {signal.event_title}
                        </Link>
                      ) : (
                        humanize(signal.section_id)
                      )}
                    </span>
                    <time role="cell">
                      {signal.valid_until ? formatDateTime(signal.valid_until) : "Open"}
                    </time>
                    <time role="cell">{formatRelativeTime(signal.updated_at)}</time>
                  </div>
                ))}
              </div>
            ) : (
              <p className="empty-copy">No current verified Signals appear on this page.</p>
            )}
            <ExplorePagination
              ariaLabel="Recent Signal pagination"
              current={data.signals.page}
              pageCount={data.signals.page_count}
              previousLabel="Newer Signals"
              nextLabel="More Signals"
              previousHref={exploreHref(data, {
                signalPage: data.signals.page - 1,
              })}
              nextHref={exploreHref(data, {
                signalPage: data.signals.page + 1,
              })}
            />
          </section>
        </article>
      </SiteShell>
    </>
  );
}

function EventGroupCard({ group }: { group: ExploreEventGroup }) {
  return (
    <article className="event-signal-card">
      <header>
        <p className="eyebrow">
          <span>{humanize(group.event_type)}</span>
          <span>{humanize(group.selection_reason)}</span>
        </p>
        <h3>{group.title}</h3>
        <p className="event-signal-summary">
          {group.is_exclusive_slate ? "Mutually exclusive outcome slate" : "Related source markets"}
          {` · ${formatCompactNumber(group.volume_24h)} traded in 24h`}
        </p>
      </header>
      <ol className="event-member-list">
        {group.members.map((member) => {
          const delta = member.delta_24h_percentage_points;
          return (
            <li key={member.topic_id}>
              <div>
                <small>{humanize(member.selection_reason)}</small>
                <Link href={topicPath(member.title, member.topic_id)}>
                  {member.option_label || member.title}
                </Link>
                {member.option_label ? <p>{member.title}</p> : null}
              </div>
              <strong>{formatTopicProbability(member.current_probability)}</strong>
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
            Observed {formatRelativeTime(group.latest_observed_at)} · resolves{" "}
            {formatDateTime(group.resolution_deadline_at)}
          </span>
          {group.suppressed_member_count > 0 ? (
            <strong>+{group.suppressed_member_count} source outcomes folded into this event</strong>
          ) : (
            <strong>Complete event view</strong>
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
}: {
  ariaLabel: string;
  current: number;
  pageCount: number;
  previousLabel: string;
  nextLabel: string;
  previousHref: string;
  nextHref: string;
}) {
  if (pageCount <= 1) return null;
  return (
    <nav aria-label={ariaLabel} className="directory-pagination">
      {current > 1 ? <Link href={previousHref}>← {previousLabel}</Link> : <span />}
      <span>
        Page {current} of {pageCount}
      </span>
      {current < pageCount ? <Link href={nextHref}>{nextLabel} →</Link> : <span />}
    </nav>
  );
}

function exploreHref(
  data: ExploreData,
  override: { topicPage?: number; signalPage?: number },
): string {
  const query = new URLSearchParams({ as_of: data.ranking_as_of });
  const topicPage = override.topicPage ?? data.topics.page;
  const signalPage = override.signalPage ?? data.signals.page;
  if (topicPage > 1) query.set("topic_page", String(topicPage));
  if (signalPage > 1) query.set("signal_page", String(signalPage));
  return `/explore?${query.toString()}`;
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

function formatCompactNumber(value: number): string {
  return new Intl.NumberFormat("en", {
    notation: "compact",
    maximumFractionDigits: 1,
    style: "currency",
    currency: "USD",
  }).format(value);
}

function deskName(deskId: string): string {
  if (deskId.includes("expectation")) return "Expectations";
  if (deskId.includes("rule")) return "Rules";
  if (deskId.includes("research")) return "Research";
  return humanize(deskId);
}
