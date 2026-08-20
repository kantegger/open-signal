"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  FrontPageData,
  EditionRecordData,
  PublicationClaimRecord,
  PublicationContext,
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

      <div className={`dashboard-top${compact ? " current-dashboard-top" : ""}${secondary.items.length || hasLiveTape ? " has-side" : ""}`}>
        <div className="dashboard-lead-column">
          <section className="slot-region lead-region" aria-label={locale === "zh-Hant" ? "主訊號" : "Lead signal"}>
            {lead.items.length ? (
              lead.items.map((item) => <PlanRenderer item={item} key={item.id} onEvidence={onEvidence} />)
            ) : (
              <SparseLead data={data} />
            )}
          </section>
          {compact && research.length ? (
            <ResearchWatch
              featured
              items={research}
              total={context.counts.research_screening}
            />
          ) : null}
          {compact && (monitoredTopics.length || context.claims.length) ? (
            <SignalPulse
              asOf={context.captured_at ?? data.snapshot.composed_at}
              claims={context.claims}
              observations={monitoredTopics}
            />
          ) : null}
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
                observations={monitoredTopics}
                onEvidence={onEvidence}
              />
            ) : null}
          </div>
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
          <SourceCoverageBand coverage={context.coverage} />
          <EditionCadence archive={data.archive} currentSnapshotId={data.snapshot.id} />
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

function SignalPulse({
  asOf,
  claims,
  observations,
}: {
  asOf: string;
  claims: PublicationClaimRecord[];
  observations: PublicationExpectationObservation[];
}) {
  const { locale } = useLocale();
  const measured = observations.filter((observation) => (
    observation.delta_24h_percentage_points != null
  ));
  const rising = measured.filter((observation) => observation.delta_24h_percentage_points! > 0).length;
  const falling = measured.filter((observation) => observation.delta_24h_percentage_points! < 0).length;
  const largestMove = [...measured].sort((left, right) => (
    Math.abs(right.delta_24h_percentage_points!) - Math.abs(left.delta_24h_percentage_points!)
  ))[0];
  const nearestResolution = observations
    .filter((observation) => Number.isFinite(Date.parse(observation.resolution_deadline_at)))
    .sort((left, right) => Date.parse(left.resolution_deadline_at) - Date.parse(right.resolution_deadline_at))[0];
  const asOfTimestamp = Date.parse(asOf);
  const deadlineBuckets = [
    { label: locale === "zh-Hant" ? "24 小時" : "24h", days: 1 },
    { label: locale === "zh-Hant" ? "3 天" : "3d", days: 3 },
    { label: locale === "zh-Hant" ? "7 天" : "7d", days: 7 },
    { label: locale === "zh-Hant" ? "30 天" : "30d", days: 30 },
    { label: locale === "zh-Hant" ? "更久" : "later", days: Number.POSITIVE_INFINITY },
  ].map((bucket, index, buckets) => {
    const lowerDays = index === 0 ? 0 : buckets[index - 1].days;
    const count = observations.filter((observation) => {
      const deadline = Date.parse(observation.resolution_deadline_at);
      if (!Number.isFinite(deadline) || !Number.isFinite(asOfTimestamp)) return false;
      const days = (deadline - asOfTimestamp) / 86_400_000;
      return days >= lowerDays && days < bucket.days;
    }).length;
    return { ...bucket, count };
  });
  const maxDeadlineCount = Math.max(...deadlineBuckets.map((bucket) => bucket.count), 1);
  const evidenceReferences = claims.reduce((total, claim) => total + claim.evidence_count, 0);
  const latestClaim = [...claims]
    .filter((claim) => Number.isFinite(Date.parse(claim.updated_at ?? claim.issued_at)))
    .sort((left, right) => (
      Date.parse(right.updated_at ?? right.issued_at) - Date.parse(left.updated_at ?? left.issued_at)
    ))[0];

  return (
    <section className="signal-pulse" aria-labelledby="signal-pulse-title">
      <RegionHeader
        id="signal-pulse-title"
        title={locale === "zh-Hant" ? "↕ 訊號脈動" : "↕ Signal pulse"}
        note={locale === "zh-Hant" ? "衍生脈絡 · 並非新主張" : "Derived context · not a new Claim"}
      />
      <div className="signal-pulse-grid signal-pulse-visual-grid">
        <article className="breadth-visual">
          <span>{locale === "zh-Hant" ? "24 小時廣度" : "24h breadth"}</span>
          <strong className="signal-pulse-breadth">
            <b className="trend-up">↗ {rising}</b>
            <b className="trend-down">↘ {falling}</b>
            <b className="trend-neutral">— {observations.length - rising - falling}</b>
          </strong>
          <div aria-hidden="true" className="breadth-bar">
            <i className="breadth-up" style={{ flexGrow: rising }} />
            <i className="breadth-flat" style={{ flexGrow: observations.length - rising - falling }} />
            <i className="breadth-down" style={{ flexGrow: falling }} />
          </div>
          <small>{locale === "zh-Hant" ? "上升 · 下降 · 持平或缺少可比較基準" : "up · down · flat or without a comparable baseline"}</small>
        </article>
        <article>
          <span>{locale === "zh-Hant" ? "最大觀測變化" : "Largest observed move"}</span>
          {largestMove ? (
            <>
              <strong className={deltaClass(largestMove.delta_24h_percentage_points)}>
                {trendGlyph(largestMove.delta_24h_percentage_points)} {formatDelta(largestMove.delta_24h_percentage_points!)}
                <small>{formatProbability(largestMove.current_probability)}</small>
              </strong>
              <Link href={topicPath(largestMove.title, largestMove.id, locale)}>{largestMove.title}</Link>
            </>
          ) : (
            <><strong>—</strong><small>{locale === "zh-Hant" ? "目前沒有完整的 24 小時比較。" : "No complete 24h comparison is available."}</small></>
          )}
        </article>
        <article className="deadline-visual">
          <span>{locale === "zh-Hant" ? "結算期限分布" : "Resolution horizon"}</span>
          <div className="deadline-bars" aria-label={locale === "zh-Hant" ? "按時間分組的結算期限" : "Resolution deadlines grouped by time"}>
            {deadlineBuckets.map((bucket) => (
              <span key={bucket.label}>
                <i style={{ blockSize: `${Math.max(5, bucket.count / maxDeadlineCount * 100)}%` }} />
                <b>{bucket.count}</b>
                <small>{bucket.label}</small>
              </span>
            ))}
          </div>
          {nearestResolution ? (
            <Link href={topicPath(nearestResolution.title, nearestResolution.id, locale)}>
              {locale === "zh-Hant" ? "最近" : "Nearest"} · {formatRelativeTime(nearestResolution.resolution_deadline_at, locale)} · {nearestResolution.title}
            </Link>
          ) : (
            <small>{locale === "zh-Hant" ? "沒有附帶有效期限。" : "No active deadline is attached."}</small>
          )}
        </article>
        <article>
          <span>{locale === "zh-Hant" ? "判斷基礎" : "Judgment base"}</span>
          <strong>{claims.length} {locale === "zh-Hant" ? "筆已驗證" : "verified"} <small>· {evidenceReferences} {locale === "zh-Hant" ? "筆證據參照" : "evidence refs"}</small></strong>
          {latestClaim ? (
            <Link href={signalPath(latestClaim.statement, latestClaim.id, locale)}>
              {locale === "zh-Hant" ? "最新" : "Latest"} · {formatRelativeTime(latestClaim.updated_at ?? latestClaim.issued_at, locale)}
            </Link>
          ) : <small>{locale === "zh-Hant" ? "目前沒有主張紀錄。" : "No current Claim record."}</small>}
        </article>
      </div>
    </section>
  );
}

function ExpectationMovementBoard({
  items,
  observations,
  onEvidence,
}: {
  items: RenderPlanItem[];
  observations: PublicationExpectationObservation[];
  onEvidence: OpenEvidence;
}) {
  const { locale } = useLocale();
  const ranked = [...observations]
    .filter((observation) => observation.current_probability != null)
    .sort((left, right) => (
      Math.abs(right.delta_24h_percentage_points ?? 0) - Math.abs(left.delta_24h_percentage_points ?? 0)
    ))
    .slice(0, 8);
  const measured = ranked.filter((observation) => observation.delta_24h_percentage_points != null);
  const rising = measured.filter((observation) => observation.delta_24h_percentage_points! > 0).length;
  const falling = measured.filter((observation) => observation.delta_24h_percentage_points! < 0).length;
  const flat = ranked.length - rising - falling;
  const maxMove = Math.max(...ranked.map((observation) => Math.abs(observation.delta_24h_percentage_points ?? 0)), 1);
  const plansByTopic = new Map(
    uniquePlans(items).flatMap((item) => item.topic?.id ? [[item.topic.id, item] as const] : []),
  );

  return (
    <section className="expectation-board" aria-labelledby="expectation-board-title">
      <RegionHeader
        id="expectation-board-title"
        title={locale === "zh-Hant" ? "↕ 預期變動" : "↕ Expectation movement"}
        note={locale === "zh-Hant" ? "重要變動優先 · 24 小時" : "Material moves first · 24 hours"}
      />
      <div className="expectation-breadth" aria-label={locale === "zh-Hant" ? "預期變動廣度" : "Expectation movement breadth"}>
        <strong className="trend-up"><b>{rising}</b><span>{locale === "zh-Hant" ? "上升" : "up"}</span></strong>
        <strong className="trend-down"><b>{falling}</b><span>{locale === "zh-Hant" ? "下降" : "down"}</span></strong>
        <strong className="trend-neutral"><b>{flat}</b><span>{locale === "zh-Hant" ? "持平／無基準" : "flat / no baseline"}</span></strong>
      </div>
      <ol className="movement-list">
        {ranked.map((observation) => {
          const delta = observation.delta_24h_percentage_points;
          const magnitude = Math.abs(delta ?? 0) / maxMove * 50;
          const plan = plansByTopic.get(observation.id);
          return (
            <li key={observation.id}>
              <Link href={topicPath(observation.title, observation.id, locale)}>
                <span>{humanize(observation.event_type, locale)}</span>
                <strong>{observation.title}</strong>
              </Link>
              <div className="movement-measure">
                <div aria-hidden="true" className="movement-track">
                  <i className="movement-negative" style={{ inlineSize: delta != null && delta < 0 ? `${magnitude}%` : 0 }} />
                  <i className="movement-positive" style={{ inlineSize: delta != null && delta > 0 ? `${magnitude}%` : 0 }} />
                </div>
                <span className={deltaClass(delta)}>{trendGlyph(delta)} {delta == null ? "—" : formatDelta(delta)}</span>
              </div>
              <strong className="movement-probability">{formatProbability(observation.current_probability)}</strong>
              <MiniSparkline observation={observation} />
              {plan?.trust.claim_id ? (
                <button
                  aria-label={`${locale === "zh-Hant" ? "開啟證據" : "Open evidence for"} ${plan.headline}`}
                  onClick={(event) => onEvidence(plan.trust.claim_id!, event.currentTarget)}
                  type="button"
                ><Icon name="evidence" size={15} /></button>
              ) : <span />}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function MiniSparkline({
  observation,
}: {
  observation: PublicationExpectationObservation;
}) {
  const quality = observation.series_quality;
  const seriesPoints = observation.series.flatMap(([rawTimestamp, value]) => {
    const timestamp = Date.parse(rawTimestamp);
    return Number.isFinite(timestamp) && Number.isFinite(value)
      ? [{ timestamp, value }]
      : [];
  });
  const values = seriesPoints.map((point) => point.value);
  const observedRange = values.length ? Math.max(...values) - Math.min(...values) : 0;
  const temporalOrderValid = seriesPoints.every((point, index) => (
    index === 0 || point.timestamp > seriesPoints[index - 1].timestamp
  ));
  const temporalRange = seriesPoints.length >= 2
    ? seriesPoints.at(-1)!.timestamp - seriesPoints[0].timestamp
    : 0;
  const hasCompleteHistory = quality?.coverage_status === "complete"
    && seriesPoints.length >= 2
    && observedRange > 0
    && temporalOrderValid
    && temporalRange > 0;
  if (!hasCompleteHistory) {
    const hasDirection = observation.delta_24h_percentage_points != null;
    const fallbackDescription = hasDirection
      ? `${observation.title}: only the observed 24-hour direction is shown; a complete seven-day series is unavailable.`
      : `${observation.title}: no complete history or 24-hour baseline is available.`;
    return (
      <span
        aria-label={fallbackDescription}
        className={`sparkline-fallback ${deltaClass(observation.delta_24h_percentage_points)}`}
        data-series-status={quality?.coverage_status ?? "unverified"}
        title={fallbackDescription}
      >
        <span aria-hidden="true">{trendGlyph(observation.delta_24h_percentage_points)}</span>
        <small>{hasDirection ? "Δ24h" : "no baseline"}</small>
      </span>
    );
  }
  const width = 92;
  const height = 22;
  const min = Math.min(...values);
  const range = observedRange;
  const firstTimestamp = seriesPoints[0].timestamp;
  const coordinates = seriesPoints.map((point) => {
    const x = ((point.timestamp - firstTimestamp) / temporalRange) * width;
    const y = height - 2 - ((point.value - min) / range) * (height - 4);
    return { timestamp: point.timestamp, x: x.toFixed(1), y: y.toFixed(1) };
  });
  const finalPoint = coordinates.at(-1) ?? { x: String(width), y: String(height / 2) };
  const description = `${observation.title}: seven-day source history from ${quality.observation_count} observations, ${formatProbability(values[0])} to ${formatProbability(values.at(-1))}.`;
  return (
    <span
      className="sparkline-evidence"
      data-series-status={quality.coverage_status}
    >
      <svg
        aria-label={description}
        className={`mini-sparkline ${deltaClass(observation.delta_24h_percentage_points)}`}
        role="img"
        viewBox={`0 0 ${width} ${height}`}
      >
        <title>{description}</title>
        <line className="sparkline-baseline" x1="0" x2={width} y1={height - 1} y2={height - 1} />
        <polyline
          fill="none"
          points={coordinates.map((point) => `${point.x},${point.y}`).join(" ")}
          vectorEffect="non-scaling-stroke"
        />
        {coordinates.map((point, index) => (
          <circle
            className="sparkline-sample"
            cx={point.x}
            cy={point.y}
            key={`${point.timestamp}-${index}`}
            r="0.65"
          />
        ))}
        <circle className="sparkline-terminal" cx={finalPoint.x} cy={finalPoint.y} r="1.8" />
      </svg>
      <small>{`7d · ${quality.observation_count} obs`}</small>
    </span>
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
  const rising = claims.filter((claim) => claim.direction === "up").length;
  const falling = claims.filter((claim) => claim.direction === "down").length;
  const neutral = claims.length - rising - falling;
  const evidenceTotal = claims.reduce((total, claim) => total + claim.evidence_count, 0);
  const desks = [...new Set(claims.map((claim) => claim.section_id))];
  return (
    <section className="claim-ledger-panel" aria-labelledby="claim-ledger-title">
      <RegionHeader
        id="claim-ledger-title"
        title={locale === "zh-Hant" ? "已驗證判斷帳本" : "Verified judgment ledger"}
        note={locale === "zh-Hant" ? `${claims.length} 筆有效 Claim 紀錄 · 無重複投影` : `${claims.length} active Claim records · no duplicate projections`}
      />
      <div className="ledger-summary" aria-label={locale === "zh-Hant" ? "判斷帳本摘要" : "Judgment ledger summary"}>
        <div className="ledger-direction-summary">
          <span>{locale === "zh-Hant" ? "方向分布" : "Direction mix"}</span>
          <strong><b className="trend-up">↗ {rising}</b><b className="trend-down">↘ {falling}</b><b className="trend-neutral">— {neutral}</b></strong>
          <div aria-hidden="true">
            <i className="ledger-up" style={{ flexGrow: rising }} />
            <i className="ledger-neutral" style={{ flexGrow: neutral }} />
            <i className="ledger-down" style={{ flexGrow: falling }} />
          </div>
        </div>
        <div className="ledger-desk-summary">
          <span>{locale === "zh-Hant" ? "編輯台涵蓋" : "Desk coverage"}</span>
          <strong>{desks.length}</strong>
          <p>{desks.map((desk) => sectionName(desk, locale)).join(" · ")}</p>
        </div>
        <div className="ledger-evidence-summary">
          <span>{locale === "zh-Hant" ? "證據參照" : "Evidence references"}</span>
          <strong>{evidenceTotal}</strong>
          <p>{locale === "zh-Hant" ? `平均每筆 ${(evidenceTotal / Math.max(claims.length, 1)).toFixed(1)}` : `${(evidenceTotal / Math.max(claims.length, 1)).toFixed(1)} per Claim`}</p>
        </div>
      </div>
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
  const transitions = new Map<string, { previous: string; current: string; count: number }>();
  for (const rule of rules) {
    const previous = rule.previous_state ?? "recorded";
    const key = `${previous}:${rule.current_state}`;
    const existing = transitions.get(key);
    transitions.set(key, { previous, current: rule.current_state, count: (existing?.count ?? 0) + 1 });
  }
  return (
    <section className="watch-panel rule-watch" aria-labelledby="rule-watch-title">
      <RegionHeader id="rule-watch-title" title={locale === "zh-Hant" ? "⚖ 規則監測" : "⚖ Rule watch"} note={locale === "zh-Hant" ? "已標準化的來源事實" : "Normalized source facts"} />
      <div className="rule-transition-summary" aria-label={locale === "zh-Hant" ? "規則狀態遷移摘要" : "Rule state transition summary"}>
        {[...transitions.values()].map((transition) => (
          <div key={`${transition.previous}:${transition.current}`}>
            <span>{humanize(transition.previous, locale)}</span>
            <i aria-hidden="true"><b>{transition.count}</b><span>→</span></i>
            <strong>{humanize(transition.current, locale)}</strong>
          </div>
        ))}
      </div>
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

function SourceCoverageBand({
  coverage,
}: {
  coverage: PublicationContext["coverage"];
}) {
  const { locale } = useLocale();
  if (!coverage.length) return null;
  return (
    <section className="source-coverage-band" aria-labelledby="source-coverage-title">
      <header>
        <h2 id="source-coverage-title">{locale === "zh-Hant" ? "◌ 來源涵蓋" : "◌ Source coverage"}</h2>
        <p>{locale === "zh-Hant" ? "原始攝取 · 僅供脈絡，不是已發布 Claims" : "Raw intake · context only, not published Claims"}</p>
      </header>
      <div
        data-count={coverage.length}
        data-density={collectionDensity(coverage.length, "grid")}
      >
        {coverage.map((source) => {
          const hourly = source.hourly_records ?? [];
          const maxHourly = Math.max(...hourly.map((bucket) => bucket.count), 1);
          return (
            <article key={source.source_slug}>
              <span>{sourceGlyph(source.source_slug)} {source.source_label}</span>
              <strong>{source.records_24h}<small> / 24h</small></strong>
              {hourly.length ? (
                <div
                  aria-label={`${source.source_label}: ${source.records_24h} ${locale === "zh-Hant" ? "筆紀錄，按小時分布" : "records distributed by hour"}`}
                  className="source-activity-chart"
                  role="img"
                >
                  {hourly.map((bucket) => (
                    <i
                      aria-hidden="true"
                      key={bucket.hour}
                      style={{ blockSize: `${bucket.count ? Math.max(8, bucket.count / maxHourly * 100) : 2}%` }}
                    />
                  ))}
                </div>
              ) : (
                <div aria-hidden="true" className="source-activity-fallback"><i style={{ inlineSize: source.records_24h ? "100%" : 0 }} /></div>
              )}
              <small>{source.records_total} {locale === "zh-Hant" ? "筆已擷取" : "captured"} · {formatRelativeTime(source.latest_ingested_at, locale)}</small>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function EditionCadence({
  archive,
  currentSnapshotId,
}: {
  archive: FrontPageData["archive"];
  currentSnapshotId: string;
}) {
  const { locale } = useLocale();
  if (!archive.length) return null;
  const chronological = [...archive].reverse();
  const maxClaims = Math.max(...chronological.map((edition) => edition.claim_count), 1);
  const latestDiff = archive[0]?.claim_diff;
  return (
    <section className="edition-cadence" aria-labelledby="edition-cadence-title">
      <header>
        <div>
          <h2 id="edition-cadence-title">{locale === "zh-Hant" ? "▥ 期次節奏" : "▥ Edition cadence"}</h2>
          <p>{locale === "zh-Hant" ? "不可變快照 · 最近在右" : "Immutable snapshots · newest at right"}</p>
        </div>
        {latestDiff ? (
          <p className="latest-edition-diff">
            <b className="trend-up">+{latestDiff.added}</b>
            <span>{locale === "zh-Hant" ? "新增" : "added"}</span>
            <b>{latestDiff.retained}</b>
            <span>{locale === "zh-Hant" ? "保留" : "retained"}</span>
            <b className="trend-down">−{latestDiff.retired}</b>
            <span>{locale === "zh-Hant" ? "退出" : "retired"}</span>
          </p>
        ) : null}
      </header>
      <div
        className="edition-cadence-track"
        style={{ gridTemplateColumns: `repeat(${chronological.length}, minmax(42px, 1fr))` }}
      >
        {chronological.map((edition) => (
          <Link
            aria-label={`${locale === "zh-Hant" ? "開啟期次" : "Open Edition"} ${formatDateTime(edition.composed_at, locale)}; ${edition.claim_count} Claims`}
            className={edition.id === currentSnapshotId ? "is-current" : ""}
            data-status={edition.status}
            href={editionPath(edition.id, locale)}
            key={edition.id}
          >
            <i style={{ blockSize: `${Math.max(12, edition.claim_count / maxClaims * 100)}%` }} />
            <span>{edition.claim_count}</span>
            <time>{new Date(edition.composed_at).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", timeZone: "UTC" })} UTC</time>
          </Link>
        ))}
      </div>
    </section>
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

function sourceGlyph(slug: string): string {
  if (slug === "federal-register") return "⚖";
  if (slug === "openalex") return "◎";
  if (slug === "clinicaltrials-gov") return "✚";
  if (slug === "polymarket-gamma") return "↗";
  return "•";
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
