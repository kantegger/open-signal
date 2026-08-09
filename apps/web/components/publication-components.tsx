"use client";

import type { JsonRecord, RenderPlanItem } from "../lib/api";
import { formatDateTime, formatRelativeTime, humanize } from "../lib/i18n";
import { Icon } from "./icons";

export type OpenEvidence = (claimId: string, trigger: HTMLElement) => void;

export function PlanRenderer({
  item,
  onEvidence,
}: {
  item: RenderPlanItem;
  onEvidence: OpenEvidence;
}) {
  if (item.slot_id === "secondary") {
    return <SecondarySignal item={item} onEvidence={onEvidence} />;
  }
  switch (item.component_family) {
    case "signal-hero":
      return <SignalHero item={item} onEvidence={onEvidence} />;
    case "time-series":
      return <TimeSeries item={item} onEvidence={onEvidence} />;
    case "state-transition":
      return <StateTransition item={item} onEvidence={onEvidence} />;
    case "document-change":
      return <DocumentChange item={item} onEvidence={onEvidence} />;
    case "signal-feed":
      return <SignalFeedCard item={item} onEvidence={onEvidence} />;
    case "evidence-relationship":
      return <EvidenceRelationship item={item} onEvidence={onEvidence} />;
    case "resolution-comparison":
      return <ResolutionComparison item={item} onEvidence={onEvidence} />;
    case "archive-snapshot":
      return <ArchiveSnapshot item={item} onEvidence={onEvidence} />;
    default:
      return <ConservativeFallback item={item} onEvidence={onEvidence} />;
  }
}

export function SignalHero({ item, onEvidence }: ComponentProps) {
  const fields = item.display_fields;
  const current = probability(fields.current_probability ?? fields.probability);
  const start = probability(fields.start_probability);
  const delta = number(fields.delta_percentage_points) ?? (
    current !== null && start !== null ? current - start : null
  );
  const series = seriesPoints(fields.series);
  const observation = string(fields.primary_observation ?? fields.observation ?? item.dek);
  const analysis = string(fields.analysis);
  const assessment = string(fields.assessment);

  return (
    <article className={`signal-hero ${sectionClass(item.section_id)}`} data-component-family="signal-hero">
      <div className="hero-primary">
        <p className="eyebrow">Lead signal</p>
        <h1>{item.headline}</h1>
        {current !== null ? (
          <div className="hero-change" aria-label={changeLabel(start, current, delta)}>
            {start !== null ? <span>{formatPercent(start)}</span> : null}
            {start !== null ? <span className="change-arrow">→</span> : null}
            <strong>{formatPercent(current)}</strong>
            {string(fields.window) ? <small>· {humanize(string(fields.window))}</small> : null}
          </div>
        ) : null}

        {series.length >= 2 ? (
          <ProbabilityChart points={series} title={`${item.headline} probability series`} />
        ) : current !== null ? (
          <ProbabilityScale current={current} start={start} />
        ) : null}
      </div>

      <div className="hero-layers">
        <HeroLayer
          item={item}
          label="Observed"
          onEvidence={onEvidence}
          text={observation || "The verified observation is recorded in the Claim."}
        />
        <HeroLayer
          item={item}
          label="Analysis"
          onEvidence={onEvidence}
          text={analysis || "No additional analytical inference was published."}
        />
        <HeroLayer
          item={item}
          label="Open Signal assessment"
          onEvidence={onEvidence}
          text={assessment || "The Claim is presented without an additional editorial assessment."}
        />
      </div>
    </article>
  );
}

function HeroLayer({ item, label, text, onEvidence }: ComponentProps & { label: string; text: string }) {
  const isObservation = label === "Observed";
  return (
    <section className="hero-layer">
      <p className="eyebrow">{label}</p>
      <p className="hero-layer-copy">{text}</p>
      <dl className="hero-layer-meta">
        {isObservation ? <><dt>Source</dt><dd>{item.trust.source_label}</dd></> : null}
        <dt>Confidence</dt><dd>{confidence(item)}</dd>
        {isObservation ? <><dt>Evidence</dt><dd>{item.trust.evidence_count}</dd></> : null}
        <dt>{isObservation ? "Data as of" : "Assessed"}</dt>
        <dd>{formatRelativeTime(isObservation ? item.times.data_as_of : item.times.assessed_at)}</dd>
      </dl>
      {item.trust.claim_id ? (
        <button
          aria-label={isObservation ? "View full evidence" : `Open ${label} evidence`}
          className="layer-evidence"
          onClick={(event) => onEvidence(item.trust.claim_id!, event.currentTarget)}
          type="button"
        >
          <span>{isObservation ? "View full evidence" : "Open evidence"}</span>
          <Icon name="arrow" size={18} />
        </button>
      ) : null}
    </section>
  );
}

function SecondarySignal({ item, onEvidence }: ComponentProps) {
  const fields = item.display_fields;
  const current = probability(fields.current_probability ?? fields.probability);
  const start = probability(fields.start_probability);
  const previousState = string(fields.previous_state);
  const currentState = string(fields.current_state);
  const observation = string(fields.observation ?? fields.analysis ?? item.dek);
  return (
    <article className={`publication-module secondary-signal ${sectionClass(item.section_id)}`} data-component-family={item.component_family}>
      <p className="eyebrow">Secondary signal · {sectionName(item.section_id)}</p>
      <h2>{item.headline}</h2>
      {current !== null ? (
        <p className="secondary-change">
          {start !== null ? <><span>{formatPercent(start)}</span><span>→</span></> : null}
          <strong>{formatPercent(current)}</strong>
          {number(fields.delta_percentage_points) !== null ? <small>{signed(number(fields.delta_percentage_points)!)}pp</small> : null}
        </p>
      ) : previousState || currentState ? (
        <p className="secondary-transition">
          <span>{humanize(previousState || "previous")}</span><span>→</span><strong>{humanize(currentState || "current")}</strong>
        </p>
      ) : null}
      {observation ? <p className="secondary-observation"><span>Observed</span>{observation}</p> : null}
      <TrustLine item={item} onEvidence={onEvidence} />
    </article>
  );
}

export function TimeSeries({ item, onEvidence }: ComponentProps) {
  const fields = item.display_fields;
  const current = probability(fields.current_probability ?? fields.probability);
  const start = probability(fields.start_probability);
  const delta = number(fields.delta_percentage_points) ?? (
    current !== null && start !== null ? current - start : null
  );
  const series = seriesPoints(fields.series);
  return (
    <article className={`publication-module time-series-module ${sectionClass(item.section_id)}`} data-component-family="time-series">
      <ModuleHeading item={item} title="Probability move" />
      <div className="metric-summary">
        {start !== null ? <span>{formatPercent(start)}</span> : null}
        {start !== null && current !== null ? <span className="change-arrow">→</span> : null}
        {current !== null ? <strong>{formatPercent(current)}</strong> : null}
        {delta !== null ? <small>{signed(delta)} percentage points</small> : null}
      </div>
      {series.length >= 2 ? (
        <ProbabilityChart points={series} title={`${item.headline} time series`} compact />
      ) : current !== null ? (
        <ProbabilityScale current={current} start={start} />
      ) : (
        <p className="module-copy">{string(fields.observation ?? fields.analysis ?? item.dek) || "Verified change; no chart series was published."}</p>
      )}
      <TrustLine item={item} onEvidence={onEvidence} />
    </article>
  );
}

export function StateTransition({ item, onEvidence }: ComponentProps) {
  const fields = item.display_fields;
  const stages = transitionStages(fields);
  return (
    <article className={`publication-module state-module ${sectionClass(item.section_id)}`} data-component-family="state-transition">
      <ModuleHeading item={item} title="State transition" />
      <ol className="state-timeline">
        {stages.map((stage, index) => (
          <li className={stage.current ? "is-current" : ""} key={`${stage.label}-${index}`}>
            <span className="state-marker" />
            <div>
              <strong>{stage.label}</strong>
              {stage.date ? <time>{stage.date}</time> : null}
              {stage.detail ? <p>{stage.detail}</p> : null}
            </div>
          </li>
        ))}
      </ol>
      {stages.length === 0 ? <p className="module-copy">{string(fields.observation ?? item.dek) || "The authoritative state changed."}</p> : null}
      <TrustLine item={item} onEvidence={onEvidence} />
    </article>
  );
}

export function DocumentChange({ item, onEvidence }: ComponentProps) {
  const fields = item.display_fields;
  const oldText = string(fields.old_text ?? fields.previous_text);
  const newText = string(fields.new_text ?? fields.current_text);
  const summary = string(fields.diff_summary ?? fields.change_summary ?? fields.observation);
  return (
    <article className={`publication-module document-change-module ${sectionClass(item.section_id)}`} data-component-family="document-change">
      <ModuleHeading item={item} title="Material document change" />
      {oldText || newText ? (
        <div className="document-diff">
          <div><span>Old</span><p>{oldText || "Not published"}</p></div>
          <div><span>New</span><p>{newText || "Not published"}</p></div>
        </div>
      ) : null}
      {summary ? <p className="change-classification"><span>{humanize(string(fields.change_type) || "Material")}</span> — {summary}</p> : null}
      <TrustLine item={item} onEvidence={onEvidence} />
    </article>
  );
}

export function SignalFeedRow({ item, onEvidence }: ComponentProps) {
  const fields = item.display_fields;
  const trend = string(fields.trend);
  const changed = string(fields.change_value ?? fields.current_state);
  return (
    <article className={`feed-row ${sectionClass(item.section_id)}`} data-component-family="signal-feed">
      <time dateTime={item.times.data_as_of ?? undefined}>{shortTime(item.times.data_as_of ?? item.times.assessed_at)}</time>
      <div className="feed-copy">
        <span className="section-name">{sectionName(item.section_id)}</span>
        <button
          className="feed-headline"
          disabled={!item.trust.claim_id}
          onClick={(event) => item.trust.claim_id && onEvidence(item.trust.claim_id, event.currentTarget)}
          type="button"
        >
          {item.headline}
        </button>
      </div>
      <span className={`feed-state trend-${trend || "neutral"}`}>
        {trend === "up" ? "↑ up" : trend === "down" ? "↓ down" : changed || "verified"}
      </span>
    </article>
  );
}

export function SignalFeedCard({ item, onEvidence }: ComponentProps) {
  return (
    <article className={`publication-module signal-feed-card ${sectionClass(item.section_id)}`} data-component-family="signal-feed">
      <ModuleHeading item={item} title={sectionName(item.section_id)} />
      <p className="module-copy">{string(item.display_fields.observation ?? item.display_fields.change_value ?? item.dek) || item.headline}</p>
      <TrustLine item={item} onEvidence={onEvidence} />
    </article>
  );
}

export function EvidenceRelationship({ item, onEvidence }: ComponentProps) {
  const events = evidenceEvents(item.display_fields.events);
  return (
    <article className={`publication-module evidence-relationship-module ${sectionClass(item.section_id)}`} data-component-family="evidence-relationship">
      <ModuleHeading item={item} title="Evidence timeline" />
      {events.length ? (
        <ol className="evidence-timeline">
          {events.map((event, index) => (
            <li key={`${event.title}-${index}`}>
              <span className="timeline-dot" />
              <time>{event.date || "Date recorded in evidence"}</time>
              <strong>{event.title}</strong>
              {event.source ? <small>{event.source}</small> : null}
            </li>
          ))}
        </ol>
      ) : <p className="module-copy">{string(item.display_fields.analysis ?? item.display_fields.observation ?? item.dek) || "A typed relationship is supported by the linked evidence."}</p>}
      <TrustLine item={item} onEvidence={onEvidence} />
    </article>
  );
}

export function ResolutionComparison({ item, onEvidence }: ComponentProps) {
  const fields = item.display_fields;
  const probabilityValue = probability(fields.final_probability);
  return (
    <article className={`publication-module resolution-module ${sectionClass(item.section_id)}`} data-component-family="resolution-comparison">
      <ModuleHeading item={item} title="Forecast vs outcome" />
      <div className="resolution-grid">
        <div><span>Original claim</span><strong>{string(fields.expectation_title ?? fields.original_claim) || item.headline}</strong></div>
        <div><span>Outcome</span><strong>{string(fields.outcome) || "Resolved"}</strong></div>
        <div><span>Final probability</span><strong>{probabilityValue !== null ? formatPercent(probabilityValue) : "—"}</strong></div>
        <div><span>Score</span><strong>{string(fields.error_metric ?? fields.brier_contribution) || "—"}</strong></div>
      </div>
      <p className="source-locked"><Icon name="lock" size={15} /> Source locked at resolution.</p>
      <TrustLine item={item} onEvidence={onEvidence} />
    </article>
  );
}

export function ArchiveSnapshot({ item, onEvidence }: ComponentProps) {
  return (
    <article className="publication-module archive-snapshot-module" data-component-family="archive-snapshot">
      <ModuleHeading item={item} title="Archive snapshot" />
      <dl className="archive-stats">
        <div><dt>Edition</dt><dd>{string(item.display_fields.edition_date) || "Recorded"}</dd></div>
        <div><dt>Primary signal</dt><dd>{string(item.display_fields.primary_signal) || item.headline}</dd></div>
        <div><dt>Resolved</dt><dd>{string(item.display_fields.resolved_claim_ids) || "—"}</dd></div>
        <div><dt>Corrections</dt><dd>{string(item.display_fields.correction_count) || "0"}</dd></div>
      </dl>
      <TrustLine item={item} onEvidence={onEvidence} />
    </article>
  );
}

export function ConservativeFallback({ item, onEvidence }: ComponentProps) {
  return (
    <article className={`publication-module conservative-module ${sectionClass(item.section_id)}`}>
      <ModuleHeading item={item} title="Verified signal" />
      <p className="module-copy">{string(item.display_fields.observation ?? item.dek) || item.headline}</p>
      <TrustLine item={item} onEvidence={onEvidence} />
    </article>
  );
}

export function TrustLine({ item, onEvidence, prominent = false }: ComponentProps & { prominent?: boolean }) {
  const claimId = item.trust.claim_id;
  return (
    <div className={`trust-line${prominent ? " trust-line-prominent" : ""}`}>
      <span><b>Source</b> {item.trust.source_label}</span>
      <span><b>Confidence</b> {confidence(item)}</span>
      <span><b>Evidence</b> {item.trust.evidence_count}</span>
      <span title={formatDateTime(item.times.data_as_of)}><b>Data as of</b> {formatRelativeTime(item.times.data_as_of)}</span>
      {item.freshness_state === "aging" ? <span className="aging-label">Aging · still valid</span> : null}
      {claimId ? (
        <button
          className="evidence-button"
          onClick={(event) => onEvidence(claimId, event.currentTarget)}
          type="button"
        >
          <Icon name="evidence" size={prominent ? 20 : 15} />
          {prominent ? "View full evidence" : `Claim ${claimId.slice(0, 8)}`}
          <Icon name="arrow" size={prominent ? 20 : 14} />
        </button>
      ) : null}
    </div>
  );
}

function ModuleHeading({ item, title }: { item: RenderPlanItem; title: string }) {
  return (
    <header className="module-heading">
      <p className="eyebrow">{title}</p>
      <h2>{item.headline}</h2>
      {item.dek ? <p>{item.dek}</p> : null}
    </header>
  );
}

function ProbabilityChart({
  points,
  title,
  compact = false,
}: {
  points: ChartPoint[];
  title: string;
  compact?: boolean;
}) {
  const width = 720;
  const height = compact ? 210 : 280;
  const left = 48;
  const right = 18;
  const top = 18;
  const bottom = 34;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const coordinates = points.map((point, index) => ({
    ...point,
    x: left + (index / Math.max(points.length - 1, 1)) * plotWidth,
    y: top + (1 - Math.max(0, Math.min(100, point.value)) / 100) * plotHeight,
  }));
  const path = coordinates.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ");
  const first = coordinates[0];
  const last = coordinates.at(-1);
  const labels = [points[0], points[Math.floor((points.length - 1) / 2)], points.at(-1)].filter(Boolean) as ChartPoint[];

  return (
    <figure className="probability-chart">
      <svg aria-label={title} role="img" viewBox={`0 0 ${width} ${height}`}>
        {[0, 25, 50, 75, 100].map((tick) => {
          const y = top + (1 - tick / 100) * plotHeight;
          return (
            <g key={tick}>
              <line className="chart-grid" x1={left} x2={width - right} y1={y} y2={y} />
              <text className="chart-axis" x={left - 9} y={y + 4}>{tick}%</text>
            </g>
          );
        })}
        <line className="chart-axis-line" x1={left} x2={left} y1={top} y2={height - bottom} />
        <line className="chart-axis-line" x1={left} x2={width - right} y1={height - bottom} y2={height - bottom} />
        <path className="chart-line" d={path} />
        {first ? <circle className="chart-point chart-point-start" cx={first.x} cy={first.y} r="4" /> : null}
        {last ? <circle className="chart-point" cx={last.x} cy={last.y} r="5" /> : null}
        {labels.map((point, index) => (
          <text className="chart-date" key={`${point.label}-${index}`} textAnchor={index === 0 ? "start" : index === labels.length - 1 ? "end" : "middle"} x={left + (index / Math.max(labels.length - 1, 1)) * plotWidth} y={height - 10}>
            {point.label}
          </text>
        ))}
      </svg>
    </figure>
  );
}

function ProbabilityScale({ current, start }: { current: number; start: number | null }) {
  return (
    <div className="probability-scale" aria-label={`Current probability ${formatPercent(current)}`}>
      <div className="scale-track">
        {start !== null ? <span className="scale-start" style={{ insetInlineStart: `${clamp(start)}%` }} /> : null}
        <span className="scale-current" style={{ insetInlineStart: `${clamp(current)}%` }} />
      </div>
      <div className="scale-labels"><span>0%</span><span>50%</span><span>100%</span></div>
    </div>
  );
}

interface ComponentProps {
  item: RenderPlanItem;
  onEvidence: OpenEvidence;
}

interface ChartPoint { label: string; value: number }
interface Stage { label: string; date?: string; detail?: string; current: boolean }
interface TimelineEvent { date?: string; title: string; source?: string }

function seriesPoints(value: unknown): ChartPoint[] {
  if (!Array.isArray(value)) return [];
  const points: ChartPoint[] = [];
  for (const [index, raw] of value.entries()) {
    if (Array.isArray(raw)) {
      const numeric = probability(raw[1]);
      if (numeric !== null) points.push({ label: shortDate(raw[0]) || String(index + 1), value: numeric });
      continue;
    }
    if (raw && typeof raw === "object") {
      const record = raw as JsonRecord;
      const numeric = probability(record.value ?? record.probability ?? record.y ?? record.current_probability);
      if (numeric !== null) points.push({ label: shortDate(record.timestamp ?? record.date ?? record.x) || String(index + 1), value: numeric });
    }
  }
  return points;
}

function transitionStages(fields: JsonRecord): Stage[] {
  if (Array.isArray(fields.stages)) {
    return fields.stages.flatMap((raw, index) => {
      if (!raw || typeof raw !== "object") return [];
      const record = raw as JsonRecord;
      return [{
        label: string(record.label ?? record.state ?? record.name) || `Stage ${index + 1}`,
        date: shortDate(record.date ?? record.at),
        detail: string(record.detail ?? record.description) || undefined,
        current: Boolean(record.current) || index === (fields.stages as unknown[]).length - 1,
      }];
    });
  }
  const previous = string(fields.previous_state);
  const current = string(fields.current_state);
  const values: Stage[] = [];
  if (previous) values.push({ label: humanize(previous), date: shortDate(fields.previous_date), current: false });
  if (current) values.push({ label: humanize(current), date: shortDate(fields.transition_date ?? fields.effective_at), detail: string(fields.observation) || undefined, current: true });
  return values;
}

function evidenceEvents(value: unknown): TimelineEvent[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((raw) => {
    if (!raw || typeof raw !== "object") return [];
    const record = raw as JsonRecord;
    const title = string(record.title ?? record.event ?? record.description);
    return title ? [{ date: shortDate(record.date ?? record.at), title, source: string(record.source) || undefined }] : [];
  });
}

function probability(value: unknown): number | null {
  const numeric = number(value);
  if (numeric === null) return null;
  return Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
}

function number(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value.replace("%", ""));
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function string(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function formatPercent(value: number): string {
  return `${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)}%`;
}

function signed(value: number): string {
  return `${value > 0 ? "+" : ""}${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)}`;
}

function clamp(value: number): number {
  return Math.max(0, Math.min(100, value));
}

function changeLabel(start: number | null, current: number, delta: number | null): string {
  if (start === null) return `Current probability ${formatPercent(current)}`;
  return `Probability changed from ${formatPercent(start)} to ${formatPercent(current)}${delta === null ? "" : `, ${signed(delta)} percentage points`}`;
}

function confidence(item: RenderPlanItem): string {
  const label = item.trust.confidence_label || item.trust.epistemic_status;
  if (label) return humanize(label);
  if (item.trust.confidence === null || item.trust.confidence === undefined) return "Not scored";
  return item.trust.confidence >= 0.8 ? "High" : item.trust.confidence >= 0.55 ? "Medium" : "Low";
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

function shortDate(value: unknown): string {
  const raw = string(value);
  if (!raw) return "";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric" }).format(date);
}

function shortTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(date);
}
