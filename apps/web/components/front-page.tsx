"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  FrontPageData,
  EditionRecordData,
  PublicationClaimRecord,
  PublicationContext,
  PublicationExpectationEvent,
  PublicationExpectationObservation,
  PublicationSlot,
  RenderPlanItem,
  SeoIndexData,
  SlotType,
} from "../lib/api";
import { fetchCurrentFrontPage } from "../lib/api";
import { collectionDensity } from "../lib/collection-density";
import { formatDateTime, formatRelativeTime, humanize, localePath } from "../lib/i18n";
import { editionPath, signalPath, topicPath } from "../lib/urls";
import { DirectionalStatement } from "./directional-statement";
import { Icon } from "./icons";
import { useLocale } from "./locale-provider";
import { PlanRenderer, SignalFeedRow, type OpenEvidence } from "./publication-components";
import { SiteShell } from "./site-shell";

const EvidenceSheet = dynamic(() => import("./evidence-sheet"), { ssr: false });
const POLL_INTERVAL_MS = 5 * 60_000;

interface Selection {
  claimId: string;
  trigger: HTMLElement;
}

type TopicIndexItem = SeoIndexData["topics"][number];

export function FrontPage({
  editionRecord,
  initialData,
  initialTopics = [],
  live = true,
}: {
  editionRecord?: Pick<
    EditionRecordData,
    "first_published_at" | "payload_hash" | "record_class" | "events"
  >;
  initialData: FrontPageData | null;
  initialTopics?: TopicIndexItem[];
  live?: boolean;
}) {
  const { locale, text } = useLocale();
  const [data, setData] = useState<FrontPageData | null>(initialData);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [selection, setSelection] = useState<Selection | null>(null);
  const etagRef = useRef<string | null>(null);
  const loadingRef = useRef(false);
  const selectionRef = useRef<Selection | null>(null);
  const pendingSnapshotRef = useRef<FrontPageData | null>(null);
  const initialRequestRef = useRef<ReturnType<typeof fetchCurrentFrontPage> | null>(null);

  useEffect(() => {
    selectionRef.current = selection;
  }, [selection]);

  const applyRefresh = useCallback((result: Awaited<ReturnType<typeof fetchCurrentFrontPage>>) => {
    if (result.etag) etagRef.current = result.etag;
    if (result.data) {
      if (selectionRef.current) {
        pendingSnapshotRef.current = result.data;
      } else {
        startTransition(() => setData(result.data));
      }
    }
    setError(null);
  }, []);

  const applyRefreshError = useCallback((reason: unknown) => {
    if (reason instanceof DOMException && reason.name === "AbortError") return;
    setError(
      reason instanceof Error
        ? reason.message
        : locale === "zh-Hant"
          ? "出版服務沒有回應。"
          : "The publication service did not respond.",
    );
  }, [locale]);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    try {
      const result = await fetchCurrentFrontPage(signal, etagRef.current, locale);
      applyRefresh(result);
    } catch (reason) {
      applyRefreshError(reason);
    } finally {
      loadingRef.current = false;
    }
  }, [applyRefresh, applyRefreshError, locale]);

  const retry = useCallback(async () => {
    setRetrying(true);
    try {
      await refresh();
    } finally {
      setRetrying(false);
    }
  }, [refresh]);

  useEffect(() => {
    if (!live) return;
    let cancelled = false;
    if (!initialData && !loadingRef.current) {
      loadingRef.current = true;
      initialRequestRef.current ??= fetchCurrentFrontPage(undefined, etagRef.current, locale);
      void initialRequestRef.current
        .then((result) => {
          if (!cancelled) applyRefresh(result);
        })
        .catch((reason: unknown) => {
          if (!cancelled) applyRefreshError(reason);
        })
        .finally(() => {
          if (!cancelled) loadingRef.current = false;
        });
    }
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, POLL_INTERVAL_MS);
    const handleVisibility = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      cancelled = true;
      loadingRef.current = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [applyRefresh, applyRefreshError, initialData, live, locale, refresh]);

  const openEvidence: OpenEvidence = useCallback((claimId, trigger) => {
    setSelection({ claimId, trigger });
  }, []);

  const closeEvidence = useCallback(() => {
    const trigger = selectionRef.current?.trigger;
    setSelection(null);
    trigger?.focus();
    if (pendingSnapshotRef.current) {
      const pending = pendingSnapshotRef.current;
      pendingSnapshotRef.current = null;
      startTransition(() => setData(pending));
    }
  }, []);

  if (!data && error) {
    return <FrontPageError error={error} onRetry={() => void retry()} retrying={retrying} />;
  }
  if (!data) return <FrontPageSkeleton />;

  return (
    <SiteShell active={live ? "current" : "archive"} systemState={data.system_state.status}>
      {error ? (
        <div className="publication-warning" role="status">
          <span>
            {locale === "zh-Hant"
              ? "最近一次檢查失敗；目前顯示的是上一個已驗證快照。"
              : "The latest check failed. This is the last verified snapshot."}
          </span>
          <button disabled={retrying} onClick={() => void retry()} type="button">
            <Icon name="refresh" size={15} /> {retrying ? text.checking : locale === "zh-Hant" ? "再次檢查" : "Check again"}
          </button>
        </div>
      ) : null}
      {locale === "zh-Hant" && data.locale.fallback_used ? (
        <p className="translation-fallback-notice" role="note">
          {text.originalEnglishNotice}
        </p>
      ) : null}
      <Publication
        compact={live}
        data={data}
        editionRecord={editionRecord}
        onEvidence={openEvidence}
        topics={initialTopics}
      />
      {selection ? (
        <EvidenceSheet claimId={selection.claimId} onClose={closeEvidence} />
      ) : null}
    </SiteShell>
  );
}

function Publication({
  compact,
  data,
  editionRecord,
  onEvidence,
  topics,
}: {
  compact: boolean;
  data: FrontPageData;
  editionRecord?: Pick<
    EditionRecordData,
    "first_published_at" | "payload_hash" | "record_class" | "events"
  >;
  onEvidence: OpenEvidence;
  topics: TopicIndexItem[];
}) {
  const { locale, text } = useLocale();
  const slots = useMemo(() => new Map(data.slots.map((slot) => [slot.type, slot])), [data.slots]);
  const lead = slot(slots, "lead");
  const secondary = slot(slots, "secondary");
  const liveFeed = slot(slots, "live_feed");
  const digest = slot(slots, "digest");
  const main = slot(slots, "main");
  const utility = slot(slots, "utility");
  const archivePlans = slot(slots, "archive");
  const lastMaterialUpdate = latestMaterialUpdate(data.slots) ?? data.snapshot.composed_at;
  const activeItems = data.slots
    .filter((publicationSlot) => publicationSlot.type !== "archive")
    .flatMap((publicationSlot) => publicationSlot.items);
  const uniqueClaims = new Set(activeItems.flatMap((item) => item.claim_ids)).size;
  const context = data.publication_context ?? legacyPublicationContext(data.snapshot.composed_at);
  const monitoredTopics = compact
    ? expectationMonitorItems(context.expectations, topics, data.slots)
    : [];
  const research = context.research
    .filter((item) => Boolean(item.headline && item.entity && item.evidence_count))
    .slice(0, 6);
  const hasLiveTape = compact && Boolean(liveFeed.items.length || monitoredTopics.length);
  const currentIndexItems = uniquePlans([...digest.items, ...main.items, ...utility.items]).slice(0, 8);
  const observationCount = context.counts.expectation_observations + context.counts.rules_tracked;
  const leadTopicId = lead.items[0]?.topic?.id;
  const featuredEvent = context.expectation_events?.find((event) => (
    event.members.some((member) => member.topic_id === leadTopicId)
  ));
  const featuredEventTopicIds = new Set(featuredEvent?.members.map((member) => member.topic_id) ?? []);

  return (
    <article className="front-page" data-snapshot-id={data.snapshot.id}>
      {!compact ? (
        <header className="edition-header">
          <div>
            <p className="eyebrow">{locale === "zh-Hant" ? "不可變的典藏期次" : "Immutable archive edition"}</p>
            <h1>{`${text.edition} · ${data.snapshot.edition_date}`}</h1>
          </div>
          <dl className="edition-times">
            <div><dt>{text.composed}</dt><dd>{formatDateTime(data.snapshot.composed_at, locale)}</dd></div>
            <div><dt>{text.lastVerified}</dt><dd>{formatRelativeTime(lastMaterialUpdate, locale)}</dd></div>
          </dl>
        </header>
      ) : null}

      {!compact && editionRecord ? (
        <EditionIntegrity record={editionRecord} />
      ) : null}

      <dl className={`coverage-strip${compact ? " coverage-current" : ""}`} aria-label={locale === "zh-Hant" ? "出版涵蓋範圍" : "Publication coverage"}>
        {compact ? (
          <>
            <div className="coverage-live"><dt>{locale === "zh-Hant" ? "出版狀態" : "Publication state"}</dt><dd><span className={`status-dot status-${data.system_state.status}`} /> {locale === "zh-Hant" ? "即時" : "Live"}</dd></div>
            <div><dt>{locale === "zh-Hant" ? "有效區段" : "Active Sections"}</dt><dd>{data.sections.length}</dd></div>
            <div><dt>{locale === "zh-Hant" ? "已驗證主張" : "Verified Claims"}</dt><dd>{context.counts.verified_claims || uniqueClaims}</dd></div>
            <div><dt>{locale === "zh-Hant" ? "來源觀測" : "Source Observations"}</dt><dd>{observationCount || monitoredTopics.length}</dd></div>
            <div><dt>{locale === "zh-Hant" ? "研究篩選" : "Research Screening"}</dt><dd>{context.counts.research_screening}</dd></div>
            <div><dt>{locale === "zh-Hant" ? "24 小時紀錄" : "Records · 24h"}</dt><dd>{context.counts.source_records_24h}</dd></div>
            <div><dt>{locale === "zh-Hant" ? "快照擷取" : "Snapshot captured"}</dt><dd>{formatRelativeTime(context.captured_at ?? data.snapshot.composed_at, locale)}</dd></div>
          </>
        ) : (
          <>
            <div><dt>{locale === "zh-Hant" ? "有效區段" : "Active Sections"}</dt><dd>{data.sections.length}</dd></div>
            <div><dt>{locale === "zh-Hant" ? "已驗證訊號" : "Verified signals"}</dt><dd>{uniqueClaims}</dd></div>
            <div><dt>{locale === "zh-Hant" ? "即時變化" : "Live changes"}</dt><dd>{liveFeed.items.length}</dd></div>
            <div><dt>{locale === "zh-Hant" ? "最近實質更新" : "Last material update"}</dt><dd>{formatRelativeTime(lastMaterialUpdate, locale)}</dd></div>
            <div><dt>{locale === "zh-Hant" ? "快照" : "Snapshot"}</dt><dd>{data.snapshot.id.slice(0, 8)}</dd></div>
          </>
        )}
      </dl>

      <div className={`dashboard-top${compact ? " current-dashboard-top" : ""}${secondary.items.length ? " has-side" : ""}`}>
        <div className="dashboard-lead-column">
          <section className="slot-region lead-region" aria-label={locale === "zh-Hant" ? "主訊號" : "Lead signal"}>
            {lead.items.length ? (
              lead.items.map((item) => <PlanRenderer item={item} key={item.id} onEvidence={onEvidence} />)
            ) : (
              <SparseLead data={data} />
            )}
          </section>
          {compact && featuredEvent ? <EventComparison event={featuredEvent} /> : null}
        </div>

        {secondary.items.length || hasLiveTape ? (
          <div className="dashboard-side">
            {secondary.items.length ? (
              <section className="slot-region secondary-region" aria-labelledby="secondary-title">
                <RegionHeader id="secondary-title" title={text.secondarySignals} note={`${secondary.items.length} ${text.verified}`} />
                <div
                  className="secondary-grid"
                  data-count={secondary.items.length}
                  data-density={collectionDensity(secondary.items.length, "grid")}
                >
                  {secondary.items.map((item) => <PlanRenderer item={item} key={item.id} onEvidence={onEvidence} />)}
                </div>
              </section>
            ) : null}
            {hasLiveTape ? (
              <ExpectationMovementBoard
                items={liveFeed.items}
                observations={monitoredTopics.filter((observation) => !featuredEventTopicIds.has(observation.id))}
                onEvidence={onEvidence}
              />
            ) : null}
          </div>
        ) : null}

        {compact && research.length ? (
          <ResearchWatch
            featured
            items={research}
            total={context.counts.research_screening}
          />
        ) : null}
      </div>

      {!compact && liveFeed.items.length ? <LiveFeed items={liveFeed.items} onEvidence={onEvidence} /> : null}

      {compact ? (
        <>
          <CurrentIntelligence
            context={context}
            fallbackItems={currentIndexItems}
            onEvidence={onEvidence}
          />
          <CurrentDestinations />
        </>
      ) : (
        <>
          <div className="dashboard-workspace">
            {digest.items.length ? (
              <section className="slot-region digest-region" aria-labelledby="digest-title">
                <RegionHeader id="digest-title" title={text.significantChanges} note={locale === "zh-Hant" ? "影響受監測訊號的已驗證變化" : "Verified changes impacting monitored signals"} />
                <DigestTable items={digest.items} onEvidence={onEvidence} />
              </section>
            ) : null}

            {main.items.length ? (
              <section
                className="slot-region main-region"
                aria-label={locale === "zh-Hant" ? "分析模組" : "Analysis modules"}
                data-count={main.items.length}
                data-density={collectionDensity(main.items.length, "grid")}
              >
                {main.items.map((item) => <PlanRenderer item={item} key={item.id} onEvidence={onEvidence} />)}
              </section>
            ) : null}

            {utility.items.length ? (
              <section
                className="slot-region utility-region"
                aria-label={locale === "zh-Hant" ? "即將發生與已結算訊號工具" : "Upcoming and resolved signal utilities"}
                data-count={utility.items.length}
                data-density={collectionDensity(utility.items.length, "grid")}
              >
                {utility.items.map((item) => <PlanRenderer item={item} key={item.id} onEvidence={onEvidence} />)}
              </section>
            ) : null}
          </div>

          <section
            className="slot-region archive-region"
            aria-labelledby="archive-title"
            data-count={archivePlans.items.length}
            data-density={collectionDensity(archivePlans.items.length, "grid")}
          >
            {archivePlans.items.map((item) => <PlanRenderer item={item} key={item.id} onEvidence={onEvidence} />)}
            <ArchiveTable archive={data.archive} currentSnapshotId={data.snapshot.id} isCurrent={data.snapshot.is_current} />
          </section>

          <footer className="publication-footer">
            <div>
              <p className="eyebrow">{locale === "zh-Hant" ? "編製時採用的方法" : "Method at composition"}</p>
              <p>{data.method.summary}</p>
              <span>{locale === "zh-Hant" ? "編譯器" : "Composer"} {data.method.composer_version} · {locale === "zh-Hant" ? "政策" : "policy"} {data.method.policy_version}</span>
            </div>
            <div>
              <p className="eyebrow">{locale === "zh-Hant" ? "系統狀態" : "System state"}</p>
              <strong><span className={`status-dot status-${data.system_state.status}`} /> {humanize(data.system_state.status, locale)}</strong>
              <span>{locale === "zh-Hant" ? "最近檢查" : "Last checked"} {formatRelativeTime(data.system_state.last_checked_at, locale)}</span>
            </div>
          </footer>
        </>
      )}
    </article>
  );
}

function EditionIntegrity({
  record,
}: {
  record: Pick<
    EditionRecordData,
    "first_published_at" | "payload_hash" | "record_class" | "events"
  >;
}) {
  const { locale } = useLocale();
  const latest = record.events.at(-1);
  return (
    <section className="edition-integrity" aria-label={locale === "zh-Hant" ? "期次完整性與生命週期" : "Edition integrity and lifecycle"}>
      <dl>
        <div><dt>{locale === "zh-Hant" ? "紀錄類別" : "Record class"}</dt><dd>{humanize(record.record_class, locale)}</dd></div>
        <div><dt>{locale === "zh-Hant" ? "首次發布" : "First published"}</dt><dd>{formatDateTime(record.first_published_at, locale)}</dd></div>
        <div><dt>Payload SHA-256</dt><dd title={record.payload_hash}>{record.payload_hash.slice(0, 16)}…</dd></div>
        <div><dt>{locale === "zh-Hant" ? "生命週期" : "Lifecycle"}</dt><dd>{humanize(latest?.event_type ?? "published", locale)} · {record.events.length} {locale === "zh-Hant" ? "個事件" : "events"}</dd></div>
      </dl>
      {record.events.length > 1 ? (
        <ol aria-label={locale === "zh-Hant" ? "期次生命週期事件" : "Edition lifecycle events"}>
          {record.events.map((event) => (
            <li key={event.id}>
              <span>{event.sequence_no.toString().padStart(2, "0")}</span>
              <strong>{humanize(event.event_type, locale)}</strong>
              <time>{formatDateTime(event.created_at, locale)}</time>
              {event.reason ? <em>{event.reason}</em> : null}
              {event.related_edition_id ? (
                <Link href={editionPath(event.related_edition_id, locale)}>
                  {event.related_edition_id.slice(0, 8)} →
                </Link>
              ) : null}
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}

function LiveFeed({
  items,
  onEvidence,
}: {
  items: RenderPlanItem[];
  onEvidence: OpenEvidence;
}) {
  const { text } = useLocale();
  return (
    <section className="slot-region live-feed-region" aria-labelledby="live-feed-title">
      <RegionHeader id="live-feed-title" title={text.liveFeed} note={text.recentFirst} />
      <div
        className="feed-list"
        data-count={items.length}
        data-density={collectionDensity(items.length, "list")}
      >
        {items.map((item) => <SignalFeedRow item={item} key={item.id} onEvidence={onEvidence} />)}
      </div>
    </section>
  );
}

function EventComparison({ event }: { event: PublicationExpectationEvent }) {
  const { locale } = useLocale();
  const sectionRef = useRef<HTMLElement>(null);
  const availableMembers = event.members.filter((member) => member.current_probability != null).slice(0, 5);
  const [visibleCount, setVisibleCount] = useState(Math.min(3, availableMembers.length));

  useEffect(() => {
    const section = sectionRef.current;
    if (!section || availableMembers.length < 2) return;
    const dashboard = section.closest(".current-dashboard-top");
    const companion = dashboard?.querySelector<HTMLElement>(".secondary-region");
    const measure = () => {
      const width = dashboard?.getBoundingClientRect().width ?? window.innerWidth;
      const responsiveMaximum = width <= 760 ? 3 : width < 1180 ? 4 : 5;
      if (!companion || width <= 900) {
        setVisibleCount(Math.min(availableMembers.length, responsiveMaximum));
        return;
      }
      const sectionTop = section.getBoundingClientRect().top;
      const availableHeight = Math.max(0, companion.getBoundingClientRect().bottom - sectionTop);
      const heading = section.querySelector<HTMLElement>(":scope > .region-heading")?.offsetHeight ?? 40;
      const header = section.querySelector<HTMLElement>(":scope > header")?.offsetHeight ?? 100;
      const footer = section.querySelector<HTMLElement>(":scope > footer")?.offsetHeight ?? 32;
      const rowBudget = Math.floor((availableHeight - heading - header - footer - 24) / 68);
      setVisibleCount(Math.min(availableMembers.length, responsiveMaximum, Math.max(2, rowBudget)));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(section);
    if (companion) observer.observe(companion);
    return () => observer.disconnect();
  }, [availableMembers.length]);

  const members = availableMembers.slice(0, visibleCount);
  if (availableMembers.length < 2) return null;
  return (
    <section
      className="event-comparison"
      aria-labelledby="event-comparison-title"
      data-count={members.length}
      data-density={collectionDensity(members.length, "list")}
      ref={sectionRef}
    >
      <RegionHeader id="event-comparison-title" title={locale === "zh-Hant" ? "同一事件的主要情境" : "The event, not one market"} note={humanize(event.event_type, locale)} />
      <header>
        <h2>{event.title}</h2>
        <p>{locale === "zh-Hant" ? "同一來源事件中的主要選項；僅保留領先者、顯著變動者與可信挑戰者。" : "Leading, materially moving, and credible options from the same source event."}</p>
      </header>
      <ol>
        {members.map((member) => {
          const probability = (member.current_probability ?? 0) * 100;
          return (
            <li key={member.topic_id}>
              <Link href={topicPath(member.title, member.topic_id, locale)}>
                <span><strong>{member.option_label || member.title}</strong><small>{humanize(member.selection_reason, locale)}</small></span>
                <b>{formatProbability(member.current_probability)}</b>
              </Link>
              <div aria-hidden="true"><i style={{ inlineSize: `${Math.max(1, probability)}%` }} /></div>
              <span className={deltaClass(member.delta_24h_percentage_points)}>
                {trendGlyph(member.delta_24h_percentage_points)} {member.delta_24h_percentage_points == null ? "—" : formatDelta(member.delta_24h_percentage_points)}
              </span>
              <small className="event-member-baseline">
                {member.baseline_probability_24h == null
                  ? "24h baseline unavailable"
                  : `${formatProbability(member.baseline_probability_24h)} → ${formatProbability(member.current_probability)}`}
              </small>
            </li>
          );
        })}
      </ol>
      <footer>
        <span>{event.source_label}</span>
        <span>{event.eligible_member_count} of {event.source_member_count} source options monitored</span>
        {event.folded_eligible_member_count ? <span>+ {event.folded_eligible_member_count} monitored options folded</span> : null}
        <time>{formatRelativeTime(event.latest_observed_at, locale)}</time>
      </footer>
    </section>
  );
}

function ExpectationMovementBoard({ items, observations, onEvidence }: {
  items: RenderPlanItem[];
  observations: PublicationExpectationObservation[];
  onEvidence: OpenEvidence;
}) {
  const { locale } = useLocale();
  const ranked = [...observations]
    .filter((observation) => observation.current_probability != null)
    .sort((left, right) => Math.abs(right.delta_24h_percentage_points ?? 0) - Math.abs(left.delta_24h_percentage_points ?? 0))
    .slice(0, 4);
  const plansByTopic = new Map(uniquePlans(items).flatMap((item) => item.topic?.id ? [[item.topic.id, item] as const] : []));

  return (
    <section className="expectation-board" aria-labelledby="expectation-board-title">
      <RegionHeader id="expectation-board-title" title={locale === "zh-Hant" ? "預期如何變動" : "Expectations in motion"} note={locale === "zh-Hant" ? "真實七天歷史 · 事件去重" : "Real 7-day histories · event-diverse"} />
      <div className="expectation-signal-grid">
        {ranked.map((observation) => {
          const delta = observation.delta_24h_percentage_points;
          const plan = plansByTopic.get(observation.id);
          return (
            <article key={observation.id}>
              <header><span>{humanize(observation.event_type, locale)}</span><time>{formatRelativeTime(observation.current_observed_at ?? observation.updated_at, locale)}</time></header>
              <Link href={topicPath(observation.title, observation.id, locale)}><h3>{observation.title}</h3></Link>
              <div className="expectation-signal-metric"><strong>{formatProbability(observation.current_probability)}</strong><span className={deltaClass(delta)}>{trendGlyph(delta)} {delta == null ? "—" : formatDelta(delta)} · 24h</span></div>
              <SignalHistoryFigure observation={observation} />
              <footer>
                <span>{observation.source_label}</span>
                {observation.series_quality ? <span>{observation.series_quality.observation_count} {locale === "zh-Hant" ? "筆觀測" : "observations"}</span> : null}
                {plan?.trust.claim_id ? <button aria-label={`${locale === "zh-Hant" ? "開啟證據" : "Open evidence for"} ${plan.headline}`} onClick={(event) => onEvidence(plan.trust.claim_id!, event.currentTarget)} type="button"><Icon name="evidence" size={15} /></button> : null}
              </footer>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function SignalHistoryFigure({ observation }: { observation: PublicationExpectationObservation }) {
  const { locale } = useLocale();
  const quality = observation.series_quality;
  const points = observation.series.flatMap(([rawTimestamp, value]) => {
    const timestamp = Date.parse(rawTimestamp);
    return Number.isFinite(timestamp) && Number.isFinite(value) ? [{ timestamp, value }] : [];
  });
  const ordered = points.every((point, index) => index === 0 || point.timestamp > points[index - 1].timestamp);
  if (quality?.coverage_status !== "complete" || points.length < 2 || !ordered) {
    return <div className={`signal-history-fallback ${deltaClass(observation.delta_24h_percentage_points)}`} data-series-status={quality?.coverage_status ?? "unverified"}><b>{trendGlyph(observation.delta_24h_percentage_points)}</b><span>{locale === "zh-Hant" ? "七天歷史不完整；僅顯示已觀測的 24 小時方向。" : "Seven-day history incomplete; showing only the observed 24h direction."}</span></div>;
  }
  const width = 320;
  const height = 104;
  const inset = 8;
  const firstTime = points[0].timestamp;
  const timeRange = points.at(-1)!.timestamp - firstTime;
  const coordinates = points.map((point) => ({ ...point, x: inset + ((point.timestamp - firstTime) / timeRange) * (width - inset * 2), y: inset + (1 - point.value) * (height - inset * 2) }));
  const path = coordinates.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ");
  const first = coordinates[0];
  const last = coordinates.at(-1)!;
  const description = `${observation.title}: ${formatProbability(first.value)} to ${formatProbability(last.value)} across ${quality.observation_count} source observations.`;
  return (
    <figure className={`signal-history-chart ${deltaClass(observation.delta_24h_percentage_points)}`}>
      <svg aria-label={description} role="img" viewBox={`0 0 ${width} ${height}`}>
        <title>{description}</title>
        {[25, 50, 75].map((tick) => <line className="signal-history-grid" key={tick} x1="0" x2={width} y1={height - tick / 100 * height} y2={height - tick / 100 * height} />)}
        <path d={path} fill="none" vectorEffect="non-scaling-stroke" />
        {coordinates.map((point, index) => <circle cx={point.x} cy={point.y} key={`${point.timestamp}-${index}`} r="1.25" />)}
        <circle className="is-terminal" cx={last.x} cy={last.y} r="3.5" />
      </svg>
      <figcaption><span>{formatProbability(first.value)}</span><b>{locale === "zh-Hant" ? "7 天真實歷史" : "real 7d history"}</b><span>{formatProbability(last.value)}</span></figcaption>
    </figure>
  );
}

function CurrentIntelligence({
  context,
  fallbackItems,
  onEvidence,
}: {
  context: PublicationContext;
  fallbackItems: RenderPlanItem[];
  onEvidence: OpenEvidence;
}) {
  const { locale } = useLocale();
  const claims = context.claims.slice(0, 12);
  const rules = context.rules.slice(0, 8);
  if (!claims.length && !rules.length && !fallbackItems.length) return null;
  return (
    <div className={`current-intelligence-grid${rules.length ? "" : " current-intelligence-single"}`}>
      {claims.length ? (
        <ClaimLedger claims={claims} onEvidence={onEvidence} />
      ) : fallbackItems.length ? (
        <section className="current-snapshot-index" aria-labelledby="current-index-title">
          <RegionHeader id="current-index-title" title={locale === "zh-Hant" ? "已驗證訊號索引" : "Verified signal index"} note={locale === "zh-Hant" ? `${fallbackItems.length} 筆不同的目前紀錄` : `${fallbackItems.length} distinct current records`} />
          <DigestTable
            ariaLabel={locale === "zh-Hant" ? "已驗證訊號索引" : "Verified signal index"}
            headlineLabel={locale === "zh-Hant" ? "訊號" : "Signal"}
            items={fallbackItems}
            onEvidence={onEvidence}
          />
        </section>
      ) : null}
      {rules.length ? <div className="watch-stack single-watch"><RuleWatch rules={rules} /></div> : null}
    </div>
  );
}

function ClaimLedger({
  claims,
  onEvidence,
}: {
  claims: PublicationClaimRecord[];
  onEvidence: OpenEvidence;
}) {
  const { locale } = useLocale();
  return (
    <section className="claim-ledger-panel" aria-labelledby="claim-ledger-title">
      <RegionHeader
        id="claim-ledger-title"
        title={locale === "zh-Hant" ? "已驗證判斷帳本" : "Verified judgment ledger"}
        note={locale === "zh-Hant" ? `${claims.length} 筆有效 Claim 紀錄 · 無重複投影` : `${claims.length} active Claim records · no duplicate projections`}
      />
      <div
        className="claim-ledger"
        role="table"
        aria-label={locale === "zh-Hant" ? "已驗證判斷帳本" : "Verified judgment ledger"}
        data-count={claims.length}
        data-density={collectionDensity(claims.length, "table")}
      >
        <div className="claim-ledger-row claim-ledger-head" role="row">
          <span role="columnheader">{locale === "zh-Hant" ? "編輯台" : "Desk"}</span><span role="columnheader">Claim</span>
          <span role="columnheader">{locale === "zh-Hant" ? "變動" : "Move"}</span><span role="columnheader">{locale === "zh-Hant" ? "信心程度" : "Confidence"}</span>
          <span role="columnheader">{locale === "zh-Hant" ? "證據" : "Evidence"}</span><span role="columnheader">{locale === "zh-Hant" ? "驗證時間" : "Verified"}</span>
        </div>
        {claims.map((claim) => (
          <div className={`claim-ledger-row ${sectionClass(claim.section_id)}`} key={claim.id} role="row">
            <span role="cell">
              <b aria-hidden="true" className={`ledger-direction ${directionClass(claim.direction)}`}>{directionGlyph(claim.direction)}</b>
              <span className="sr-only">{humanize(claim.direction, locale)}{locale === "zh-Hant" ? "方向 · " : " direction · "}</span>
              {sectionName(claim.section_id, locale)}
            </span>
            <span role="cell">
              <Link href={signalPath(claim.statement, claim.id, locale)}><strong><DirectionalStatement text={claim.statement} /></strong></Link>
              <small>{claim.source_label}</small>
              <small className="collection-detail collection-detail-sparse">
                {humanize(claim.claim_type, locale)} · {humanize(claim.status, locale)}
              </small>
            </span>
            <span className={directionClass(claim.direction)} role="cell">{claim.change ?? "—"}</span>
            <span role="cell">{humanize(claim.confidence_label ?? claim.epistemic_status, locale)}</span>
            <span role="cell">
              <button
                aria-label={`${locale === "zh-Hant" ? "開啟證據" : "Open evidence for"} ${claim.statement}`}
                className="digest-evidence"
                onClick={(event) => onEvidence(claim.id, event.currentTarget)}
                type="button"
              >{claim.evidence_count}</button>
            </span>
            <time role="cell">{formatRelativeTime(claim.updated_at ?? claim.issued_at, locale)}</time>
          </div>
        ))}
      </div>
    </section>
  );
}

function RuleWatch({ rules }: { rules: PublicationContext["rules"] }) {
  const { locale } = useLocale();
  return (
    <section className="watch-panel rule-watch" aria-labelledby="rule-watch-title">
      <RegionHeader id="rule-watch-title" title={locale === "zh-Hant" ? "⚖ 規則監測" : "⚖ Rule watch"} note={locale === "zh-Hant" ? "已標準化的來源事實" : "Normalized source facts"} />
      <div
        className="watch-list"
        data-count={rules.length}
        data-density={collectionDensity(rules.length, "list")}
      >
        {rules.map((rule) => (
          <article key={rule.id}>
            <div><span>{rule.authority ?? humanize(rule.rule_type, locale)}</span><time>{formatRelativeTime(rule.transition_at ?? rule.updated_at, locale)}</time></div>
            <strong>{rule.title}</strong>
            <p><b>{humanize(rule.previous_state ?? "recorded", locale)}</b><span>→</span><b>{humanize(rule.current_state, locale)}</b></p>
            <p className="collection-detail collection-detail-sparse rule-watch-context">
              {rule.jurisdiction ? `${rule.jurisdiction} · ` : ""}{rule.source_label}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}

function ResearchWatch({
  featured = false,
  items,
  total,
}: {
  featured?: boolean;
  items: PublicationContext["research"];
  total: number;
}) {
  const { locale } = useLocale();
  const maxEvidence = Math.max(...items.map((item) => item.evidence_count), 1);
  return (
    <section
      className={`watch-panel research-watch${featured ? " research-watch-featured" : ""}`}
      aria-labelledby="research-watch-title"
    >
      <RegionHeader id="research-watch-title" title={locale === "zh-Hant" ? "🔬 研究篩選" : "🔬 Research screening"} note={locale === "zh-Hant" ? `${total} 個符合資格的公開監測 · 並非 Claims` : `${total} eligible public watches · not Claims`} />
      <div
        className="watch-list research-watch-list"
        data-count={items.length}
        data-density={collectionDensity(items.length, "grid")}
      >
        {items.map((item) => (
          <article key={item.id}>
            <div>
              <span>{researchCandidateLabel(item.candidate_type, locale)} · {humanize(item.screening_stage, locale)}</span>
              <time>{formatRelativeTime(item.detected_at, locale)}</time>
            </div>
            <strong>{item.headline}</strong>
            {item.candidate_type === "stage_transition" ? (
              <ResearchPhaseVisual
                baseline={`${item.headline} ${item.metric} ${item.baseline_label}`}
                evidenceCount={item.evidence_count}
                locale={locale}
              />
            ) : (
              <ResearchEvidenceVisual
                evidenceCount={item.evidence_count}
                maxEvidence={maxEvidence}
                locale={locale}
              />
            )}
            <p className="collection-detail collection-detail-sparse research-context">
              <span>{locale === "zh-Hant" ? "篩選脈絡" : "Screening context"}</span>
              <b>{item.topic_label}</b>
              <span>{locale === "zh-Hant" ? `${item.evidence_count} 筆來自 ${item.source_label} 的公開紀錄；尚非 Claim。` : `${item.evidence_count} public records from ${item.source_label}; not yet a Claim.`}</span>
            </p>
            <p className="research-entity"><b>{item.entity}</b><span>{item.baseline_label}</span></p>
            <p className={`research-evidence ${directionClass(item.direction)}`}>
              <b>{directionGlyph(item.direction)} {item.metric}</b>
              <span>{item.window_label} · {item.evidence_count} {locale === "zh-Hant" ? "筆紀錄" : "records"} · {item.source_label}</span>
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}

function ResearchEvidenceVisual({
  evidenceCount,
  maxEvidence,
  locale,
}: {
  evidenceCount: number;
  maxEvidence: number;
  locale: "en" | "zh-Hant";
}) {
  return (
    <div className="research-volume-visual" aria-label={`${evidenceCount} ${locale === "zh-Hant" ? "筆公開證據" : "public evidence records"}`}>
      <div aria-hidden="true"><i style={{ inlineSize: `${Math.max(5, evidenceCount / maxEvidence * 100)}%` }} /></div>
      <p><b>{evidenceCount}</b><span>{locale === "zh-Hant" ? "筆公開證據" : "public evidence records"}</span></p>
    </div>
  );
}

function ResearchPhaseVisual({
  baseline,
  evidenceCount,
  locale,
}: {
  baseline: string;
  evidenceCount: number;
  locale: "en" | "zh-Hant";
}) {
  const normalized = baseline.toLowerCase();
  const phases = [1, 2, 3, 4];
  const active = phases.filter((phase) => new RegExp(`phase\\s*${phase}|第\\s*${phase}\\s*期`, "i").test(normalized));
  return (
    <div className="research-phase-visual" aria-label={`${baseline}; ${evidenceCount} ${locale === "zh-Hant" ? "筆證據" : "evidence records"}`}>
      <div className="research-phase-track">
        {phases.map((phase) => (
          <span className={active.includes(phase) ? "is-active" : ""} key={phase}>
            <i />
            <small>{locale === "zh-Hant" ? `第 ${phase} 期` : `P${phase}`}</small>
          </span>
        ))}
      </div>
      <p><b>{evidenceCount}</b><span>{locale === "zh-Hant" ? "筆公開證據" : "public evidence records"}</span></p>
    </div>
  );
}

function CurrentDestinations() {
  const { locale } = useLocale();
  return (
    <nav aria-label={locale === "zh-Hant" ? "從目前快照繼續探索" : "Continue beyond the current snapshot"} className="current-destinations">
      <Link href={localePath("/explore", locale)}>
        <span><small>{locale === "zh-Hant" ? "探索" : "Discovery"}</small><strong>{locale === "zh-Hant" ? "探索訊號與主題" : "Explore Signals and Topics"}</strong></span>
        <Icon name="arrow" size={17} />
      </Link>
      <Link href={localePath("/editions", locale)}>
        <span><small>{locale === "zh-Hant" ? "永久紀錄" : "Permanent record"}</small><strong>{locale === "zh-Hant" ? "瀏覽期次" : "Browse Editions"}</strong></span>
        <Icon name="arrow" size={17} />
      </Link>
      <Link href={localePath("/method", locale)}>
        <span><small>{locale === "zh-Hant" ? "如何閱讀" : "How to read this"}</small><strong>{locale === "zh-Hant" ? "閱讀方法" : "Read the Method"}</strong></span>
        <Icon name="arrow" size={17} />
      </Link>
    </nav>
  );
}

function SparseLead({ data }: { data: FrontPageData }) {
  const { locale } = useLocale();
  const activeItemCount = data.slots
    .filter((publicationSlot) => publicationSlot.type !== "archive")
    .reduce((total, publicationSlot) => total + publicationSlot.items.length, 0);
  const fullyRetired = activeItemCount === 0;
  return (
    <div className="sparse-lead">
      <p className="eyebrow">{locale === "zh-Hant" ? "證據門檻 · 刻意保持稀疏" : "Evidence threshold · intentionally sparse"}</p>
      <h2>
        {fullyRetired
          ? locale === "zh-Hant" ? "目前沒有已發布的 Open Signal 判斷。" : "No Open Signal judgment is currently published."
          : locale === "zh-Hant" ? "目前沒有已驗證判斷通過主訊號門檻。" : "No verified judgment currently clears the Lead threshold."}
      </h2>
      {fullyRetired ? (
        <p>
          {locale === "zh-Hant"
            ? "先前判斷已達淘汰界線。Open Signal 發布了完整的新快照，沒有捏造替代內容；帶標籤的來源觀測與篩選脈絡仍可能保留在下方。"
            : "The previous judgment reached its retirement boundary. Open Signal published a complete new snapshot without manufacturing a replacement; labeled source observations and screening context may remain below."}
        </p>
      ) : (
        <p>
          {locale === "zh-Hant"
            ? "Open Signal 寧可讓頁面保持稀疏，也不降低證據標準。已驗證材料仍保留在下方，並顯示原始資料與評估時間。"
            : "Open Signal keeps the page sparse instead of lowering evidence standards. Verified material remains below, with its original data and assessment times."}
        </p>
      )}
      <dl>
        <div><dt>{locale === "zh-Hant" ? "有效區段" : "Active Sections"}</dt><dd>{data.sections.length || 0}</dd></div>
        <div><dt>{locale === "zh-Hant" ? "快照" : "Snapshot"}</dt><dd>{data.snapshot.id.slice(0, 8)}</dd></div>
        <div><dt>{locale === "zh-Hant" ? "編製" : "Compiled"}</dt><dd>{formatRelativeTime(data.snapshot.composed_at, locale)}</dd></div>
      </dl>
    </div>
  );
}

function DigestTable({
  ariaLabel = "Significant changes",
  headlineLabel = "Change",
  items,
  onEvidence,
}: {
  ariaLabel?: string;
  headlineLabel?: string;
  items: RenderPlanItem[];
  onEvidence: OpenEvidence;
}) {
  const { locale } = useLocale();
  return (
    <div
      className="digest-table"
      role="table"
      aria-label={ariaLabel}
      data-count={items.length}
      data-density={collectionDensity(items.length, "table")}
    >
      <div className="digest-row digest-head" role="row">
        <span role="columnheader">{locale === "zh-Hant" ? "類型" : "Type"}</span><span role="columnheader">{headlineLabel}</span>
        <span role="columnheader">{locale === "zh-Hant" ? "來源" : "Source"}</span><span role="columnheader">{locale === "zh-Hant" ? "信心程度" : "Confidence"}</span>
        <span role="columnheader">{locale === "zh-Hant" ? "證據" : "Evidence"}</span><span role="columnheader">{locale === "zh-Hant" ? "驗證時間" : "Verified"}</span>
      </div>
      {items.map((item) => (
        <div
          className={`digest-row ${sectionClass(item.section_id)}`}
          key={item.id}
          role="row"
        >
          <span role="cell">{sectionName(item.section_id, locale)}</span>
          <span role="cell">
            {item.trust.claim_id ? (
              <Link href={signalPath(item.headline, item.trust.claim_id, locale)}><strong><DirectionalStatement text={item.headline} /></strong></Link>
            ) : <strong><DirectionalStatement text={item.headline} /></strong>}
            {item.dek ? <small className="collection-detail collection-detail-sparse">{item.dek}</small> : null}
          </span>
          <span role="cell">{item.trust.source_label}</span>
          <span role="cell">{humanize(item.trust.confidence_label ?? item.trust.epistemic_status, locale)}</span>
          <span role="cell">
            {item.trust.claim_id ? (
              <button
                aria-label={`${locale === "zh-Hant" ? "開啟證據" : "Open evidence for"} ${item.headline}`}
                className="digest-evidence"
                onClick={(event) => onEvidence(item.trust.claim_id!, event.currentTarget)}
                type="button"
              >{item.trust.evidence_count}</button>
            ) : item.trust.evidence_count}
          </span>
          <span role="cell">{formatRelativeTime(item.times.assessed_at, locale)}</span>
        </div>
      ))}
    </div>
  );
}

function ArchiveTable({
  archive,
  currentSnapshotId,
  isCurrent,
}: {
  archive: FrontPageData["archive"];
  currentSnapshotId: string;
  isCurrent: boolean;
}) {
  const { locale } = useLocale();
  return (
    <div className="archive-table-wrap">
      <div className="archive-heading">
        <div><p className="eyebrow">{locale === "zh-Hant" ? "典藏快照" : "Archive snapshots"}</p><h2 id="archive-title">{locale === "zh-Hant" ? "典藏" : "Archive"}</h2></div>
        <p>{locale === "zh-Hant" ? "依時間排列、不可變的出版紀錄。" : "Chronological, immutable publication record."}</p>
      </div>
      {archive.length ? (
        <div
          className="archive-table"
          role="table"
          aria-label={locale === "zh-Hant" ? "期次典藏" : "Edition archive"}
          data-count={archive.length}
          data-density={collectionDensity(archive.length, "table")}
        >
          <div className="archive-row archive-head" role="row">
            <span role="columnheader">{locale === "zh-Hant" ? "編製" : "Composed"}</span><span role="columnheader">{locale === "zh-Hant" ? "區段" : "Sections"}</span>
            <span role="columnheader">Claims</span><span role="columnheader">{locale === "zh-Hant" ? "觸發" : "Trigger"}</span>
            <span role="columnheader">{locale === "zh-Hant" ? "狀態" : "State"}</span><span role="columnheader">{locale === "zh-Hant" ? "快照" : "Snapshot"}</span>
          </div>
          {archive.map((snapshot) => (
            <div className="archive-row" role="row" key={snapshot.id}>
              <time role="cell">{formatDateTime(snapshot.composed_at, locale)}</time>
              <span role="cell">
                {snapshot.sections.length}
                <small className="collection-detail collection-detail-sparse">
                  {snapshot.sections.map((section) => sectionName(section, locale)).join(" · ") || (locale === "zh-Hant" ? "沒有有效區段" : "No active Sections")}
                </small>
              </span>
              <span role="cell">{snapshot.claim_count}</span>
              <span role="cell">{humanize(snapshot.trigger_type, locale)}</span>
              <span role="cell">{humanize(snapshot.status, locale)}</span>
              <span role="cell">
                <Link className="archive-edition-link" href={editionPath(snapshot.id, locale)}>
                  {snapshot.id === currentSnapshotId ? <b className="current-snapshot">{isCurrent ? locale === "zh-Hant" ? "目前" : "Current" : locale === "zh-Hant" ? "本期" : "This edition"}</b> : snapshot.id.slice(0, 8)}
                </Link>
              </span>
            </div>
          ))}
        </div>
      ) : <p className="empty-copy">{locale === "zh-Hant" ? "目前尚無公開典藏快照。" : "No archived snapshots are public yet."}</p>}
    </div>
  );
}

function RegionHeader({ id, title, note }: { id: string; title: string; note?: string }) {
  return (
    <header className="region-heading">
      <h2 id={id}>{title}</h2>
      {note ? <p>{note}</p> : null}
    </header>
  );
}

function FrontPageSkeleton() {
  const { locale } = useLocale();
  return (
    <SiteShell systemState="checking">
      <div aria-busy="true" aria-label={locale === "zh-Hant" ? "正在載入目前出版內容" : "Loading current publication"} className="front-page skeleton-page">
        <div className="skeleton skeleton-title" />
        <div className="skeleton skeleton-kicker" />
        <div className="skeleton skeleton-headline" />
        <div className="skeleton skeleton-headline short" />
        <div className="skeleton skeleton-chart" />
        <div className="skeleton-row"><div className="skeleton" /><div className="skeleton" /></div>
        <p className="sr-only">{locale === "zh-Hant" ? "正在載入最近的已驗證快照。" : "Loading the latest verified snapshot."}</p>
      </div>
    </SiteShell>
  );
}

function FrontPageError({
  error,
  onRetry,
  retrying,
}: {
  error: string;
  onRetry: () => void;
  retrying: boolean;
}) {
  const { locale, text } = useLocale();
  return (
    <SiteShell systemState="unavailable">
      <div className="front-page fatal-state" role="alert">
        <p className="eyebrow">{locale === "zh-Hant" ? "出版內容暫時無法使用" : "Publication unavailable"}</p>
        <h1>{locale === "zh-Hant" ? "目前的已驗證快照無法載入。" : "The current verified snapshot could not be loaded."}</h1>
        <p>{locale === "zh-Hant" ? "典藏紀錄未被替換，系統也沒有發布不完整頁面。" : "The archive was not replaced and no partial page was published."}</p>
        <code>{error}</code>
        <button className="primary-action" disabled={retrying} onClick={onRetry} type="button">
          <Icon name="refresh" size={18} /> {retrying ? text.checking : text.retry}
        </button>
      </div>
    </SiteShell>
  );
}

function slot(slots: Map<SlotType, PublicationSlot>, type: SlotType): PublicationSlot {
  return slots.get(type) ?? {
    id: type,
    type,
    size: "medium",
    required: false,
    collapsible: true,
    desktop_order: 0,
    mobile_order: 0,
    items: [],
  };
}

function latestMaterialUpdate(slots: PublicationSlot[]): string | null {
  let latest: string | null = null;
  let timestamp = Number.NEGATIVE_INFINITY;
  for (const slotItem of slots) {
    for (const item of slotItem.items) {
      const value = item.times.materially_updated_at ?? item.times.assessed_at;
      if (!value) continue;
      const candidate = new Date(value).getTime();
      if (candidate > timestamp) {
        timestamp = candidate;
        latest = value;
      }
    }
  }
  return latest;
}

function legacyPublicationContext(capturedAt: string): PublicationContext {
  return {
    version: "legacy",
    snapshot_bound: false,
    captured_at: capturedAt,
    counts: {
      verified_claims: 0,
      expectation_observations: 0,
      rules_tracked: 0,
      research_screening: 0,
      source_records_24h: 0,
    },
    claims: [],
    expectations: [],
    expectation_events: [],
    rules: [],
    research: [],
    coverage: [],
  };
}

function uniquePlans(items: RenderPlanItem[]): RenderPlanItem[] {
  const unique = new Map<string, RenderPlanItem>();
  for (const item of items) {
    const key = item.trust.claim_id ?? item.id;
    if (!unique.has(key)) unique.set(key, item);
  }
  return [...unique.values()];
}

function expectationMonitorItems(
  captured: PublicationExpectationObservation[],
  indexedTopics: TopicIndexItem[],
  slots: PublicationSlot[],
): PublicationExpectationObservation[] {
  const topics = captured.length
    ? captured
    : indexedTopics.length
      ? indexedTopics.map(indexedExpectation)
      : embeddedTopicItems(slots);
  return [...topics]
    .sort((left, right) => {
      const moveDifference = Math.abs(right.delta_24h_percentage_points ?? 0)
        - Math.abs(left.delta_24h_percentage_points ?? 0);
      if (moveDifference) return moveDifference;
      return new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime();
    })
    .slice(0, 8);
}

function indexedExpectation(topic: TopicIndexItem): PublicationExpectationObservation {
  return {
    ...topic,
    source_market_status: topic.status,
    source_label: "Source market",
    baseline_probability_24h: null,
    series: [],
  };
}

function embeddedTopicItems(slots: PublicationSlot[]): PublicationExpectationObservation[] {
  const topics = new Map<string, PublicationExpectationObservation>();
  for (const item of slots.flatMap((publicationSlot) => publicationSlot.items)) {
    if (!item.topic || topics.has(item.topic.id)) continue;
    topics.set(item.topic.id, {
      id: item.topic.id,
      title: item.topic.title,
      event_type: item.topic.event_type,
      resolution_deadline_at: item.topic.resolution_deadline_at,
      status: "active",
      source_market_count: 1,
      source_market_status: "active",
      source_label: item.trust.source_label,
      updated_at: item.times.materially_updated_at ?? item.times.assessed_at ?? item.times.data_as_of ?? "",
      current_probability: numericField(item.display_fields.current_probability),
      current_observed_at: item.times.data_as_of,
      baseline_probability_24h: null,
      delta_24h_percentage_points: numericField(
        item.display_fields.delta_24h_percentage_points
          ?? item.display_fields.delta_percentage_points,
      ),
      baseline_observed_at: null,
      series: seriesField(item.display_fields.series),
    });
  }
  return [...topics.values()];
}

function seriesField(value: unknown): Array<[string, number]> {
  if (!Array.isArray(value)) return [];
  return value.flatMap((point) => {
    if (!Array.isArray(point) || point.length < 2) return [];
    const numeric = numericField(point[1]);
    return numeric == null ? [] : [[String(point[0]), numeric] as [string, number]];
  });
}

function numericField(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number.parseFloat(value.replace("%", ""));
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function formatProbability(value: number | null | undefined): string {
  if (value == null) return "—";
  const percentage = Math.abs(value) <= 1 ? value * 100 : value;
  return `${Math.round(percentage * 10) / 10}%`;
}

function formatDelta(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  return `${rounded > 0 ? "+" : ""}${rounded}pp`;
}

function deltaClass(value: number | null | undefined): string {
  if (value == null || value === 0) return "trend-neutral";
  return value > 0 ? "trend-up" : "trend-down";
}

function trendGlyph(value: number | null | undefined): string {
  if (value == null) return "—";
  if (Math.abs(value) < 0.05) return "→";
  return value > 0 ? "↗" : "↘";
}

function directionGlyph(direction: string): string {
  if (direction === "up") return "↗";
  if (direction === "down") return "↘";
  return "→";
}

function directionClass(direction: string): string {
  if (direction === "up") return "trend-up";
  if (direction === "down") return "trend-down";
  return "trend-neutral";
}

function sectionName(sectionId: string, locale: "en" | "zh-Hant" = "en"): string {
  if (sectionId === "rules-moved") return locale === "zh-Hant" ? "規則變化" : "Rules";
  if (sectionId === "research-frontier") return locale === "zh-Hant" ? "研究動向" : "Research";
  if (sectionId === "expectations-moved") return locale === "zh-Hant" ? "預期變化" : "Expectations";
  return humanize(sectionId, locale);
}

function sectionClass(sectionId: string): string {
  if (sectionId === "rules-moved") return "section-rules";
  if (sectionId === "research-frontier") return "section-research";
  return "section-expectations";
}

function researchCandidateLabel(candidateType: string, locale: "en" | "zh-Hant"): string {
  if (candidateType === "institution_entry") return locale === "zh-Hant" ? "機構活動" : "Institution activity";
  if (candidateType === "stage_transition") return locale === "zh-Hant" ? "試驗組合" : "Trial portfolio";
  if (candidateType === "cross_topic_relation") return locale === "zh-Hant" ? "跨主題關係" : "Cross-topic relation";
  return humanize(candidateType, locale);
}
