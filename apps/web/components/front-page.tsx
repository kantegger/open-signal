"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  FrontPageData,
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
import { copy, formatDateTime, formatRelativeTime, humanize } from "../lib/i18n";
import { editionPath, signalPath, topicPath } from "../lib/urls";
import { DirectionalStatement } from "./directional-statement";
import { Icon } from "./icons";
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
  initialData,
  initialTopics = [],
  live = true,
}: {
  initialData: FrontPageData | null;
  initialTopics?: TopicIndexItem[];
  live?: boolean;
}) {
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
    setError(reason instanceof Error ? reason.message : "The publication service did not respond.");
  }, []);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    try {
      const result = await fetchCurrentFrontPage(signal, etagRef.current);
      applyRefresh(result);
    } catch (reason) {
      applyRefreshError(reason);
    } finally {
      loadingRef.current = false;
    }
  }, [applyRefresh, applyRefreshError]);

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
      initialRequestRef.current ??= fetchCurrentFrontPage(undefined, etagRef.current);
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
  }, [applyRefresh, applyRefreshError, initialData, live, refresh]);

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
          <span>The latest check failed. This is the last verified snapshot.</span>
          <button disabled={retrying} onClick={() => void retry()} type="button">
            <Icon name="refresh" size={15} /> {retrying ? "Checking…" : "Check again"}
          </button>
        </div>
      ) : null}
      <Publication compact={live} data={data} onEvidence={openEvidence} topics={initialTopics} />
      {selection ? (
        <EvidenceSheet claimId={selection.claimId} onClose={closeEvidence} />
      ) : null}
    </SiteShell>
  );
}

function Publication({
  compact,
  data,
  onEvidence,
  topics,
}: {
  compact: boolean;
  data: FrontPageData;
  onEvidence: OpenEvidence;
  topics: TopicIndexItem[];
}) {
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
            <p className="eyebrow">Immutable archive edition</p>
            <h1>{`Edition · ${data.snapshot.edition_date}`}</h1>
          </div>
          <dl className="edition-times">
            <div><dt>{copy.en.composed}</dt><dd>{formatDateTime(data.snapshot.composed_at)}</dd></div>
            <div><dt>{copy.en.lastVerified}</dt><dd>{formatRelativeTime(lastMaterialUpdate)}</dd></div>
          </dl>
        </header>
      ) : null}

      <dl className={`coverage-strip${compact ? " coverage-current" : ""}`} aria-label="Publication coverage">
        {compact ? (
          <>
            <div className="coverage-live"><dt>Publication state</dt><dd><span className={`status-dot status-${data.system_state.status}`} /> Live</dd></div>
            <div><dt>Active Sections</dt><dd>{data.sections.length}</dd></div>
            <div><dt>Verified Claims</dt><dd>{context.counts.verified_claims || uniqueClaims}</dd></div>
            <div><dt>Source Observations</dt><dd>{observationCount || monitoredTopics.length}</dd></div>
            <div><dt>Research Screening</dt><dd>{context.counts.research_screening}</dd></div>
            <div><dt>Records · 24h</dt><dd>{context.counts.source_records_24h}</dd></div>
            <div><dt>Snapshot captured</dt><dd>{formatRelativeTime(context.captured_at ?? data.snapshot.composed_at)}</dd></div>
          </>
        ) : (
          <>
            <div><dt>Active Sections</dt><dd>{data.sections.length}</dd></div>
            <div><dt>Verified signals</dt><dd>{uniqueClaims}</dd></div>
            <div><dt>Live changes</dt><dd>{liveFeed.items.length}</dd></div>
            <div><dt>Last material update</dt><dd>{formatRelativeTime(lastMaterialUpdate)}</dd></div>
            <div><dt>Snapshot</dt><dd>{data.snapshot.id.slice(0, 8)}</dd></div>
          </>
        )}
      </dl>

      <div className={`dashboard-top${compact ? " current-dashboard-top" : ""}${secondary.items.length || hasLiveTape ? " has-side" : ""}`}>
        <div className="dashboard-lead-column">
          <section className="slot-region lead-region" aria-label="Lead signal">
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
          {compact && !research.length && (monitoredTopics.length || context.claims.length) ? (
            <SignalPulse claims={context.claims} observations={monitoredTopics} />
          ) : null}
        </div>

        {secondary.items.length || hasLiveTape ? (
          <div className="dashboard-side">
            {secondary.items.length ? (
              <section className="slot-region secondary-region" aria-labelledby="secondary-title">
                <RegionHeader id="secondary-title" title={copy.en.secondarySignals} note={`${secondary.items.length} verified`} />
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
              <LiveSignalTape
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
          <CurrentDestinations />
        </>
      ) : (
        <>
          <div className="dashboard-workspace">
            {digest.items.length ? (
              <section className="slot-region digest-region" aria-labelledby="digest-title">
                <RegionHeader id="digest-title" title={copy.en.significantChanges} note="Verified changes impacting monitored signals" />
                <DigestTable items={digest.items} onEvidence={onEvidence} />
              </section>
            ) : null}

            {main.items.length ? (
              <section
                className="slot-region main-region"
                aria-label="Analysis modules"
                data-count={main.items.length}
                data-density={collectionDensity(main.items.length, "grid")}
              >
                {main.items.map((item) => <PlanRenderer item={item} key={item.id} onEvidence={onEvidence} />)}
              </section>
            ) : null}

            {utility.items.length ? (
              <section
                className="slot-region utility-region"
                aria-label="Upcoming and resolved signal utilities"
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
              <p className="eyebrow">Method at composition</p>
              <p>{data.method.summary}</p>
              <span>Composer {data.method.composer_version} · policy {data.method.policy_version}</span>
            </div>
            <div>
              <p className="eyebrow">System state</p>
              <strong><span className={`status-dot status-${data.system_state.status}`} /> {humanize(data.system_state.status)}</strong>
              <span>Last checked {formatRelativeTime(data.system_state.last_checked_at)}</span>
            </div>
          </footer>
        </>
      )}
    </article>
  );
}

function LiveFeed({
  items,
  onEvidence,
}: {
  items: RenderPlanItem[];
  onEvidence: OpenEvidence;
}) {
  return (
    <section className="slot-region live-feed-region" aria-labelledby="live-feed-title">
      <RegionHeader id="live-feed-title" title={copy.en.liveFeed} note={copy.en.recentFirst} />
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
  claims,
  observations,
}: {
  claims: PublicationClaimRecord[];
  observations: PublicationExpectationObservation[];
}) {
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
        title="↕ Signal pulse"
        note="Derived context · not a new Claim"
      />
      <div className="signal-pulse-grid">
        <article>
          <span>24h breadth</span>
          <strong className="signal-pulse-breadth">
            <b className="trend-up">↗ {rising}</b>
            <b className="trend-down">↘ {falling}</b>
            <b className="trend-neutral">— {observations.length - rising - falling}</b>
          </strong>
          <small>up · down · flat or without a comparable baseline</small>
        </article>
        <article>
          <span>Largest observed move</span>
          {largestMove ? (
            <>
              <strong className={deltaClass(largestMove.delta_24h_percentage_points)}>
                {trendGlyph(largestMove.delta_24h_percentage_points)} {formatDelta(largestMove.delta_24h_percentage_points!)}
                <small>{formatProbability(largestMove.current_probability)}</small>
              </strong>
              <Link href={topicPath(largestMove.title, largestMove.id)}>{largestMove.title}</Link>
            </>
          ) : (
            <><strong>—</strong><small>No complete 24h comparison is available.</small></>
          )}
        </article>
        <article>
          <span>Nearest resolution</span>
          {nearestResolution ? (
            <>
              <strong>{formatRelativeTime(nearestResolution.resolution_deadline_at)}</strong>
              <Link href={topicPath(nearestResolution.title, nearestResolution.id)}>{nearestResolution.title}</Link>
            </>
          ) : (
            <><strong>—</strong><small>No active deadline is attached.</small></>
          )}
        </article>
        <article>
          <span>Judgment base</span>
          <strong>{claims.length} verified <small>· {evidenceReferences} evidence refs</small></strong>
          {latestClaim ? (
            <Link href={signalPath(latestClaim.statement, latestClaim.id)}>
              Latest · {formatRelativeTime(latestClaim.updated_at ?? latestClaim.issued_at)}
            </Link>
          ) : <small>No current Claim record.</small>}
        </article>
      </div>
    </section>
  );
}

function LiveSignalTape({
  items,
  observations,
  onEvidence,
}: {
  items: RenderPlanItem[];
  observations: PublicationExpectationObservation[];
  onEvidence: OpenEvidence;
}) {
  const verified = uniquePlans(items).slice(0, 4);
  const observationsById = new Map(observations.map((observation) => [observation.id, observation]));
  const representedTopics = new Set(
    verified.flatMap((item) => item.topic?.id ? [item.topic.id] : []),
  );
  const sourceOnly = observations
    .filter((observation) => !representedTopics.has(observation.id))
    .slice(0, Math.max(0, 8 - verified.length));

  return (
    <section className="topic-monitor" aria-labelledby="topic-monitor-title">
      <RegionHeader
        id="topic-monitor-title"
        title="↗ Live signal tape"
        note={`${verified.length} verified · ${observations.length} monitored Topics · deduplicated`}
      />
      <div
        className="topic-monitor-list live-signal-list"
        data-count={verified.length + sourceOnly.length}
        data-density={collectionDensity(verified.length + sourceOnly.length, "list")}
      >
        {verified.map((item) => (
          <VerifiedTapeRow
            item={item}
            key={item.id}
            observation={item.topic ? observationsById.get(item.topic.id) : undefined}
            onEvidence={onEvidence}
          />
        ))}
        {sourceOnly.map((observation) => <ObservedTapeRow key={observation.id} observation={observation} />)}
      </div>
    </section>
  );
}

function VerifiedTapeRow({
  item,
  observation,
  onEvidence,
}: {
  item: RenderPlanItem;
  observation?: PublicationExpectationObservation;
  onEvidence: OpenEvidence;
}) {
  const fields = item.display_fields;
  const current = numericField(fields.current_probability ?? fields.probability)
    ?? observation?.current_probability;
  const delta = numericField(fields.delta_24h_percentage_points ?? fields.delta_percentage_points)
    ?? observation?.delta_24h_percentage_points;
  const trend = textField(fields.trend);
  const directionalValue = delta ?? (trend === "up" ? 1 : trend === "down" ? -1 : null);
  const change = textField(fields.change_value);
  const currentState = textField(fields.current_state);
  const primaryMetric = current != null
    ? formatProbability(current)
    : change || humanize(currentState || "verified");
  const secondaryMetric = delta != null
    ? `${formatDelta(delta)} · 24h`
    : current != null && change
      ? change
      : `${item.trust.evidence_count} evidence`;
  const record = item.trust.claim_id
    ? <Link href={signalPath(item.headline, item.trust.claim_id)}><DirectionalStatement text={item.headline} /></Link>
    : <span>{item.headline}</span>;

  return (
    <article className={`tape-row tape-row-verified ${sectionClass(item.section_id)}`}>
      <div className="topic-monitor-identity">
        <span><b>Verified</b> · {sectionName(item.section_id)}</span>
        {record}
      </div>
      <div className="topic-monitor-state">
        <strong>{primaryMetric}</strong>
        <span className={deltaClass(directionalValue)}>{trendGlyph(directionalValue)} {secondaryMetric}</span>
      </div>
      {observation ? (
        <MiniSparkline observation={observation} />
      ) : (
        <span
          aria-label={directionalValue == null
            ? `${item.headline}: a time-series is not applicable to this verified record.`
            : `${item.headline}: verified direction only; a complete source history is unavailable.`}
          className={`sparkline-fallback ${deltaClass(directionalValue)}`}
        >
          <span aria-hidden="true">{trendGlyph(directionalValue)}</span>
          <small>{directionalValue == null ? "no series" : "direction only"}</small>
        </span>
      )}
      <div className="topic-monitor-time">
        <time>{formatRelativeTime(item.times.data_as_of ?? item.times.assessed_at)}</time>
        {item.topic ? <span>⏱ {formatRelativeTime(item.topic.resolution_deadline_at)}</span> : <span>Claim record</span>}
      </div>
      {item.trust.claim_id ? (
        <button
          aria-label={`Open evidence for ${item.headline}`}
          className="tape-action"
          onClick={(event) => onEvidence(item.trust.claim_id!, event.currentTarget)}
          type="button"
        >
          <Icon name="evidence" size={14} />
        </button>
      ) : <span className="tape-action-placeholder" />}
    </article>
  );
}

function ObservedTapeRow({
  observation,
}: {
  observation: PublicationExpectationObservation;
}) {
  return (
    <article className="tape-row tape-row-observed section-expectations">
      <div className="topic-monitor-identity">
        <span>Source · {humanize(observation.event_type)}</span>
        <Link href={topicPath(observation.title, observation.id)}>{observation.title}</Link>
      </div>
      <div className="topic-monitor-state">
        <strong>{formatProbability(observation.current_probability)}</strong>
        <span className={deltaClass(observation.delta_24h_percentage_points)}>
          {trendGlyph(observation.delta_24h_percentage_points)}{" "}
          {observation.delta_24h_percentage_points == null
            ? "baseline —"
            : `${formatDelta(observation.delta_24h_percentage_points)} · 24h`}
        </span>
      </div>
      <MiniSparkline observation={observation} />
      <div className="topic-monitor-time">
        <time>{formatRelativeTime(observation.current_observed_at ?? observation.updated_at)}</time>
        <span>⏱ {formatRelativeTime(observation.resolution_deadline_at)}</span>
      </div>
      <Link
        aria-label={`Open Topic: ${observation.title}`}
        className="tape-action"
        href={topicPath(observation.title, observation.id)}
      >
        <Icon name="arrow" size={14} />
      </Link>
    </article>
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
  const claims = context.claims.slice(0, 12);
  const rules = context.rules.slice(0, 8);
  if (!claims.length && !rules.length && !fallbackItems.length) return null;
  return (
    <div className={`current-intelligence-grid${rules.length ? "" : " current-intelligence-single"}`}>
      {claims.length ? (
        <ClaimLedger claims={claims} onEvidence={onEvidence} />
      ) : fallbackItems.length ? (
        <section className="current-snapshot-index" aria-labelledby="current-index-title">
          <RegionHeader id="current-index-title" title="Verified signal index" note={`${fallbackItems.length} distinct current records`} />
          <DigestTable
            ariaLabel="Verified signal index"
            headlineLabel="Signal"
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
  return (
    <section className="claim-ledger-panel" aria-labelledby="claim-ledger-title">
      <RegionHeader
        id="claim-ledger-title"
        title="Verified judgment ledger"
        note={`${claims.length} active Claim records · no duplicate projections`}
      />
      <div
        className="claim-ledger"
        role="table"
        aria-label="Verified judgment ledger"
        data-count={claims.length}
        data-density={collectionDensity(claims.length, "table")}
      >
        <div className="claim-ledger-row claim-ledger-head" role="row">
          <span role="columnheader">Desk</span><span role="columnheader">Claim</span>
          <span role="columnheader">Move</span><span role="columnheader">Confidence</span>
          <span role="columnheader">Evidence</span><span role="columnheader">Verified</span>
        </div>
        {claims.map((claim) => (
          <div className={`claim-ledger-row ${sectionClass(claim.section_id)}`} key={claim.id} role="row">
            <span role="cell">
              <b aria-hidden="true" className={`ledger-direction ${directionClass(claim.direction)}`}>{directionGlyph(claim.direction)}</b>
              <span className="sr-only">{humanize(claim.direction)} direction · </span>
              {sectionName(claim.section_id)}
            </span>
            <span role="cell">
              <Link href={signalPath(claim.statement, claim.id)}><strong><DirectionalStatement text={claim.statement} /></strong></Link>
              <small>{claim.source_label}</small>
              <small className="collection-detail collection-detail-sparse">
                {humanize(claim.claim_type)} · {humanize(claim.status)}
              </small>
            </span>
            <span className={directionClass(claim.direction)} role="cell">{claim.change ?? "—"}</span>
            <span role="cell">{humanize(claim.confidence_label ?? claim.epistemic_status)}</span>
            <span role="cell">
              <button
                aria-label={`Open evidence for ${claim.statement}`}
                className="digest-evidence"
                onClick={(event) => onEvidence(claim.id, event.currentTarget)}
                type="button"
              >{claim.evidence_count}</button>
            </span>
            <time role="cell">{formatRelativeTime(claim.updated_at ?? claim.issued_at)}</time>
          </div>
        ))}
      </div>
    </section>
  );
}

function RuleWatch({ rules }: { rules: PublicationContext["rules"] }) {
  return (
    <section className="watch-panel rule-watch" aria-labelledby="rule-watch-title">
      <RegionHeader id="rule-watch-title" title="⚖ Rule watch" note="Normalized source facts" />
      <div
        className="watch-list"
        data-count={rules.length}
        data-density={collectionDensity(rules.length, "list")}
      >
        {rules.map((rule) => (
          <article key={rule.id}>
            <div><span>{rule.authority ?? humanize(rule.rule_type)}</span><time>{formatRelativeTime(rule.transition_at ?? rule.updated_at)}</time></div>
            <strong>{rule.title}</strong>
            <p><b>{humanize(rule.previous_state ?? "recorded")}</b><span>→</span><b>{humanize(rule.current_state)}</b></p>
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
  return (
    <section
      className={`watch-panel research-watch${featured ? " research-watch-featured" : ""}`}
      aria-labelledby="research-watch-title"
    >
      <RegionHeader id="research-watch-title" title="🔬 Research screening" note={`${total} eligible public watches · not Claims`} />
      <div
        className="watch-list research-watch-list"
        data-count={items.length}
        data-density={collectionDensity(items.length, "grid")}
      >
        {items.map((item) => (
          <article key={item.id}>
            <div>
              <span>{researchCandidateLabel(item.candidate_type)} · {humanize(item.screening_stage)}</span>
              <time>{formatRelativeTime(item.detected_at)}</time>
            </div>
            <strong>{item.headline}</strong>
            <p className="collection-detail collection-detail-sparse research-context">
              <span>Screening context</span>
              <b>{item.topic_label}</b>
              <span>{item.evidence_count} public records from {item.source_label}; not yet a Claim.</span>
            </p>
            <p className="research-entity"><b>{item.entity}</b><span>{item.baseline_label}</span></p>
            <p className={`research-evidence ${directionClass(item.direction)}`}>
              <b>{directionGlyph(item.direction)} {item.metric}</b>
              <span>{item.window_label} · {item.evidence_count} records · {item.source_label}</span>
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}

function SourceCoverageBand({
  coverage,
}: {
  coverage: PublicationContext["coverage"];
}) {
  if (!coverage.length) return null;
  const max = Math.max(...coverage.map((source) => source.records_24h), 1);
  return (
    <section className="source-coverage-band" aria-labelledby="source-coverage-title">
      <header>
        <h2 id="source-coverage-title">◌ Source coverage</h2>
        <p>Raw intake · context only, not published Claims</p>
      </header>
      <div
        data-count={coverage.length}
        data-density={collectionDensity(coverage.length, "grid")}
      >
        {coverage.map((source) => (
          <article key={source.source_slug}>
            <span>{sourceGlyph(source.source_slug)} {source.source_label}</span>
            <strong>{source.records_24h}<small> / 24h</small></strong>
            <div aria-hidden="true"><i style={{ inlineSize: `${Math.max(4, source.records_24h / max * 100)}%` }} /></div>
            <small>{source.records_total} captured · {formatRelativeTime(source.latest_ingested_at)}</small>
          </article>
        ))}
      </div>
    </section>
  );
}

function CurrentDestinations() {
  return (
    <nav aria-label="Continue beyond the current snapshot" className="current-destinations">
      <Link href="/explore">
        <span><small>Discovery</small><strong>Explore Signals and Topics</strong></span>
        <Icon name="arrow" size={17} />
      </Link>
      <Link href="/editions">
        <span><small>Permanent record</small><strong>Browse Editions</strong></span>
        <Icon name="arrow" size={17} />
      </Link>
      <Link href="/method">
        <span><small>How to read this</small><strong>Read the Method</strong></span>
        <Icon name="arrow" size={17} />
      </Link>
    </nav>
  );
}

function SparseLead({ data }: { data: FrontPageData }) {
  const activeItemCount = data.slots
    .filter((publicationSlot) => publicationSlot.type !== "archive")
    .reduce((total, publicationSlot) => total + publicationSlot.items.length, 0);
  const fullyRetired = activeItemCount === 0;
  return (
    <div className="sparse-lead">
      <p className="eyebrow">Evidence threshold · intentionally sparse</p>
      <h2>
        {fullyRetired
          ? "No Open Signal judgment is currently published."
          : "No verified judgment currently clears the Lead threshold."}
      </h2>
      {fullyRetired ? (
        <p>
          The previous judgment reached its retirement boundary. Open Signal published a complete
          new snapshot without manufacturing a replacement; labeled source observations and
          screening context may remain below.
        </p>
      ) : (
        <p>
          Open Signal keeps the page sparse instead of lowering evidence standards. Verified
          material remains below, with its original data and assessment times.
        </p>
      )}
      <dl>
        <div><dt>Active Sections</dt><dd>{data.sections.length || 0}</dd></div>
        <div><dt>Snapshot</dt><dd>{data.snapshot.id.slice(0, 8)}</dd></div>
        <div><dt>Compiled</dt><dd>{formatRelativeTime(data.snapshot.composed_at)}</dd></div>
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
  return (
    <div
      className="digest-table"
      role="table"
      aria-label={ariaLabel}
      data-count={items.length}
      data-density={collectionDensity(items.length, "table")}
    >
      <div className="digest-row digest-head" role="row">
        <span role="columnheader">Type</span><span role="columnheader">{headlineLabel}</span>
        <span role="columnheader">Source</span><span role="columnheader">Confidence</span>
        <span role="columnheader">Evidence</span><span role="columnheader">Verified</span>
      </div>
      {items.map((item) => (
        <div
          className={`digest-row ${sectionClass(item.section_id)}`}
          key={item.id}
          role="row"
        >
          <span role="cell">{sectionName(item.section_id)}</span>
          <span role="cell">
            {item.trust.claim_id ? (
              <Link href={signalPath(item.headline, item.trust.claim_id)}><strong><DirectionalStatement text={item.headline} /></strong></Link>
            ) : <strong><DirectionalStatement text={item.headline} /></strong>}
            {item.dek ? <small className="collection-detail collection-detail-sparse">{item.dek}</small> : null}
          </span>
          <span role="cell">{item.trust.source_label}</span>
          <span role="cell">{humanize(item.trust.confidence_label ?? item.trust.epistemic_status)}</span>
          <span role="cell">
            {item.trust.claim_id ? (
              <button
                aria-label={`Open evidence for ${item.headline}`}
                className="digest-evidence"
                onClick={(event) => onEvidence(item.trust.claim_id!, event.currentTarget)}
                type="button"
              >{item.trust.evidence_count}</button>
            ) : item.trust.evidence_count}
          </span>
          <span role="cell">{formatRelativeTime(item.times.assessed_at)}</span>
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
  return (
    <div className="archive-table-wrap">
      <div className="archive-heading">
        <div><p className="eyebrow">Archive snapshots</p><h2 id="archive-title">Archive</h2></div>
        <p>Chronological, immutable publication record.</p>
      </div>
      {archive.length ? (
        <div
          className="archive-table"
          role="table"
          aria-label="Edition archive"
          data-count={archive.length}
          data-density={collectionDensity(archive.length, "table")}
        >
          <div className="archive-row archive-head" role="row">
            <span role="columnheader">Composed</span><span role="columnheader">Sections</span>
            <span role="columnheader">Claims</span><span role="columnheader">Trigger</span>
            <span role="columnheader">State</span><span role="columnheader">Snapshot</span>
          </div>
          {archive.map((snapshot) => (
            <div className="archive-row" role="row" key={snapshot.id}>
              <time role="cell">{formatDateTime(snapshot.composed_at)}</time>
              <span role="cell">
                {snapshot.sections.length}
                <small className="collection-detail collection-detail-sparse">
                  {snapshot.sections.map(sectionName).join(" · ") || "No active Sections"}
                </small>
              </span>
              <span role="cell">{snapshot.claim_count}</span>
              <span role="cell">{humanize(snapshot.trigger_type)}</span>
              <span role="cell">{humanize(snapshot.status)}</span>
              <span role="cell">
                <Link className="archive-edition-link" href={editionPath(snapshot.id)}>
                  {snapshot.id === currentSnapshotId ? <b className="current-snapshot">{isCurrent ? "Current" : "This edition"}</b> : snapshot.id.slice(0, 8)}
                </Link>
              </span>
            </div>
          ))}
        </div>
      ) : <p className="empty-copy">No archived snapshots are public yet.</p>}
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
  return (
    <SiteShell systemState="checking">
      <div aria-busy="true" aria-label="Loading current publication" className="front-page skeleton-page">
        <div className="skeleton skeleton-title" />
        <div className="skeleton skeleton-kicker" />
        <div className="skeleton skeleton-headline" />
        <div className="skeleton skeleton-headline short" />
        <div className="skeleton skeleton-chart" />
        <div className="skeleton-row"><div className="skeleton" /><div className="skeleton" /></div>
        <p className="sr-only">Loading the latest verified snapshot.</p>
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
  return (
    <SiteShell systemState="unavailable">
      <div className="front-page fatal-state" role="alert">
        <p className="eyebrow">Publication unavailable</p>
        <h1>The current verified snapshot could not be loaded.</h1>
        <p>The archive was not replaced and no partial page was published.</p>
        <code>{error}</code>
        <button className="primary-action" disabled={retrying} onClick={onRetry} type="button">
          <Icon name="refresh" size={18} /> {retrying ? "Checking…" : copy.en.retry}
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

function textField(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
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

function sectionName(sectionId: string): string {
  if (sectionId === "rules-moved") return "Rules";
  if (sectionId === "research-frontier") return "Research";
  if (sectionId === "expectations-moved") return "Expectations";
  return humanize(sectionId);
}

function sectionClass(sectionId: string): string {
  if (sectionId === "rules-moved") return "section-rules";
  if (sectionId === "research-frontier") return "section-research";
  return "section-expectations";
}

function researchCandidateLabel(candidateType: string): string {
  if (candidateType === "institution_entry") return "Institution activity";
  if (candidateType === "stage_transition") return "Trial portfolio";
  if (candidateType === "cross_topic_relation") return "Cross-topic relation";
  return humanize(candidateType);
}
