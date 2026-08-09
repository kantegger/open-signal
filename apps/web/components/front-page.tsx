"use client";

import dynamic from "next/dynamic";
import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FrontPageData, PublicationSlot, RenderPlanItem, SlotType } from "../lib/api";
import { fetchCurrentFrontPage } from "../lib/api";
import { copy, formatDateTime, formatRelativeTime, humanize } from "../lib/i18n";
import { Icon } from "./icons";
import { PlanRenderer, SignalFeedRow, type OpenEvidence } from "./publication-components";
import { SiteShell } from "./site-shell";

const EvidenceSheet = dynamic(() => import("./evidence-sheet"), { ssr: false });
const POLL_INTERVAL_MS = 5 * 60_000;

interface Selection {
  claimId: string;
  trigger: HTMLElement;
}

export function FrontPage({ initialData }: { initialData: FrontPageData | null }) {
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
  }, [applyRefresh, applyRefreshError, initialData, refresh]);

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
    <SiteShell systemState={data.system_state.status}>
      {error ? (
        <div className="publication-warning" role="status">
          <span>The latest check failed. This is the last verified snapshot.</span>
          <button disabled={retrying} onClick={() => void retry()} type="button">
            <Icon name="refresh" size={15} /> {retrying ? "Checking…" : "Check again"}
          </button>
        </div>
      ) : null}
      <Publication data={data} onEvidence={openEvidence} />
      {selection ? (
        <EvidenceSheet claimId={selection.claimId} onClose={closeEvidence} />
      ) : null}
    </SiteShell>
  );
}

function Publication({ data, onEvidence }: { data: FrontPageData; onEvidence: OpenEvidence }) {
  const slots = useMemo(() => new Map(data.slots.map((slot) => [slot.type, slot])), [data.slots]);
  const lead = slot(slots, "lead");
  const secondary = slot(slots, "secondary");
  const liveFeed = slot(slots, "live_feed");
  const digest = slot(slots, "digest");
  const main = slot(slots, "main");
  const utility = slot(slots, "utility");
  const archivePlans = slot(slots, "archive");
  const lastMaterialUpdate = latestMaterialUpdate(data.slots) ?? data.snapshot.composed_at;

  return (
    <article className="front-page" data-snapshot-id={data.snapshot.id}>
      <header className="edition-header">
        <div>
          <p className="eyebrow">Live publication</p>
          <h1>{copy.en.currentFrontPage}</h1>
        </div>
        <dl className="edition-times">
          <div><dt>{copy.en.composed}</dt><dd>{formatDateTime(data.snapshot.composed_at)}</dd></div>
          <div><dt>{copy.en.lastVerified}</dt><dd>{formatRelativeTime(lastMaterialUpdate)}</dd></div>
        </dl>
      </header>

      <div className="section-anchor" id="expectations" />
      <div className="section-anchor" id="rules" />
      <div className="section-anchor" id="research" />

      <section className="slot-region lead-region" aria-label="Lead signal">
        {lead.items.length ? (
          lead.items.map((item) => <PlanRenderer item={item} key={item.id} onEvidence={onEvidence} />)
        ) : (
          <SparseLead data={data} />
        )}
      </section>

      {liveFeed.items.length ? (
        <section className="slot-region live-feed-region" aria-labelledby="live-feed-title">
          <RegionHeader id="live-feed-title" title={copy.en.liveFeed} note={copy.en.recentFirst} />
          <div className="feed-list">
            {liveFeed.items.map((item) => <SignalFeedRow item={item} key={item.id} onEvidence={onEvidence} />)}
          </div>
        </section>
      ) : null}

      {secondary.items.length ? (
        <section className="slot-region secondary-region" aria-labelledby="secondary-title">
          <RegionHeader id="secondary-title" title={copy.en.secondarySignals} />
          <div className="secondary-grid">
            {secondary.items.map((item) => <PlanRenderer item={item} key={item.id} onEvidence={onEvidence} />)}
          </div>
        </section>
      ) : null}

      {digest.items.length ? (
        <section className="slot-region digest-region" aria-labelledby="digest-title">
          <RegionHeader id="digest-title" title={copy.en.significantChanges} note="Verified changes impacting monitored signals" />
          <DigestTable items={digest.items} onEvidence={onEvidence} />
        </section>
      ) : null}

      {main.items.length ? (
        <section className="slot-region main-region" aria-label="Analysis modules">
          {main.items.map((item) => <PlanRenderer item={item} key={item.id} onEvidence={onEvidence} />)}
        </section>
      ) : null}

      {utility.items.length ? (
        <section className="slot-region utility-region" aria-label="Upcoming and resolved signal utilities">
          {utility.items.map((item) => <PlanRenderer item={item} key={item.id} onEvidence={onEvidence} />)}
        </section>
      ) : null}

      <section className="slot-region archive-region" id="archive" aria-labelledby="archive-title">
        {archivePlans.items.map((item) => <PlanRenderer item={item} key={item.id} onEvidence={onEvidence} />)}
        <ArchiveTable archive={data.archive} />
      </section>

      <footer className="publication-footer" id="method">
        <div>
          <p className="eyebrow">Method</p>
          <p>{data.method.summary}</p>
          <span>Composer {data.method.composer_version} · policy {data.method.policy_version}</span>
        </div>
        <div>
          <p className="eyebrow">System state</p>
          <strong><span className={`status-dot status-${data.system_state.status}`} /> {humanize(data.system_state.status)}</strong>
          <span>Last checked {formatRelativeTime(data.system_state.last_checked_at)}</span>
        </div>
      </footer>
    </article>
  );
}

function SparseLead({ data }: { data: FrontPageData }) {
  const activeItemCount = data.slots
    .filter((publicationSlot) => publicationSlot.type !== "archive")
    .reduce((total, publicationSlot) => total + publicationSlot.items.length, 0);
  const fullyRetired = activeItemCount === 0;
  return (
    <div className="sparse-lead">
      <p className="eyebrow">Current front page · intentionally sparse</p>
      <h2>
        {fullyRetired
          ? "No active signal is currently published."
          : "No signal currently clears the Lead threshold."}
      </h2>
      {fullyRetired ? (
        <p>
          The previous content Section reached its retirement boundary. Open Signal published a
          complete new snapshot without manufacturing a replacement; Method, System State, and
          the immutable Archive remain available.
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

function DigestTable({ items, onEvidence }: { items: RenderPlanItem[]; onEvidence: OpenEvidence }) {
  return (
    <div className="digest-table" role="table" aria-label="Significant changes">
      <div className="digest-row digest-head" role="row">
        <span role="columnheader">Type</span><span role="columnheader">Change</span>
        <span role="columnheader">Source</span><span role="columnheader">Confidence</span>
        <span role="columnheader">Evidence</span><span role="columnheader">Verified</span>
      </div>
      {items.map((item) => (
        <button
          className={`digest-row ${sectionClass(item.section_id)}`}
          disabled={!item.trust.claim_id}
          key={item.id}
          onClick={(event) => item.trust.claim_id && onEvidence(item.trust.claim_id, event.currentTarget)}
          role="row"
          type="button"
        >
          <span role="cell">{sectionName(item.section_id)}</span>
          <strong role="cell">{item.headline}</strong>
          <span role="cell">{item.trust.source_label}</span>
          <span role="cell">{humanize(item.trust.confidence_label ?? item.trust.epistemic_status)}</span>
          <span role="cell">{item.trust.evidence_count}</span>
          <span role="cell">{formatRelativeTime(item.times.assessed_at)}</span>
        </button>
      ))}
    </div>
  );
}

function ArchiveTable({ archive }: { archive: FrontPageData["archive"] }) {
  return (
    <div className="archive-table-wrap">
      <div className="archive-heading">
        <div><p className="eyebrow">Archive snapshots</p><h2 id="archive-title">Archive</h2></div>
        <p>Chronological, immutable publication record.</p>
      </div>
      {archive.length ? (
        <div className="archive-table" role="table" aria-label="Edition archive">
          <div className="archive-row archive-head" role="row">
            <span role="columnheader">Composed</span><span role="columnheader">Sections</span>
            <span role="columnheader">Claims</span><span role="columnheader">Trigger</span>
            <span role="columnheader">State</span><span role="columnheader">Snapshot</span>
          </div>
          {archive.map((snapshot, index) => (
            <div className="archive-row" role="row" key={snapshot.id}>
              <time role="cell">{formatDateTime(snapshot.composed_at)}</time>
              <span role="cell">{snapshot.sections.length}</span>
              <span role="cell">{snapshot.claim_count}</span>
              <span role="cell">{humanize(snapshot.trigger_type)}</span>
              <span role="cell">{humanize(snapshot.status)}</span>
              <span role="cell">{index === 0 ? <b className="current-snapshot">Current</b> : snapshot.id.slice(0, 8)}</span>
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
