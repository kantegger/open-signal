// Read-only API contracts for the rolling publication surface.

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type JsonRecord = Record<string, unknown>;

export interface ClaimPageData {
  claim: {
    id: string;
    claim_type: string;
    public_statement: string;
    source_public_statement?: string;
    status: string;
    desk_id: string;
    issued_at: string;
    valid_from?: string | null;
    valid_until?: string | null;
    materially_updated_at?: string | null;
    evidence_policy_version?: "legacy" | "sealed-v1" | string;
  };
  observation: string;
  analysis: {
    summary?: string | null;
    structured_proposition: JsonRecord;
    predicate?: string;
    operator?: string;
    value?: unknown;
  };
  assessment: {
    summary?: string | null;
    confidence?: number | null;
    confidence_label?: string | null;
    epistemic_status?: string | null;
    model_version?: string | null;
    charter_version?: string | null;
  };
  evidence: EvidenceBlock;
  supporting_evidence?: EvidenceBlock;
  counterevidence: EvidenceBlock;
  evidence_record?: {
    object_hash: string;
    object_key: string;
    byte_size: number;
    content_type: string;
    policy_version: string;
    sealed_at: string;
    url?: string;
  } | null;
  uncertainty?: {
    unresolved_questions: unknown[];
    known_limitations: unknown[];
  };
  method?: {
    calculation_ids: string[];
    source_coverage: JsonRecord;
  };
  agent_lineage: {
    lineage_id: string;
    desk_id?: string | null;
    name?: string | null;
    foundation_model?: string | null;
    model_version?: string | null;
    charter_id?: string | null;
    charter_version?: string | null;
    status?: string | null;
  };
  version_history: Array<{
    version_number: number;
    public_statement: string;
    change_type: string;
    change_reason: string;
    confidence?: number | null;
    created_at: string;
  }>;
  resolution_contract?: JsonRecord | null;
  topic?: {
    id: string;
    title: string;
    event_type: string;
    resolution_deadline_at: string;
    updated_at: string;
  } | null;
  locale?: LocaleState;
}

export interface EvidenceBlock {
  items: unknown[];
  snapshot_hash?: string | null;
}

export interface LocaleState {
  requested: string;
  published: string;
  fallback_used: boolean;
  translation_provenance?: string | null;
}

export type SlotType =
  | "lead"
  | "secondary"
  | "live_feed"
  | "digest"
  | "main"
  | "utility"
  | "archive";

export type ComponentFamily =
  | "signal-hero"
  | "time-series"
  | "state-transition"
  | "document-change"
  | "signal-feed"
  | "evidence-relationship"
  | "resolution-comparison"
  | "archive-snapshot";

export interface RenderPlanItem {
  id: string;
  slot_id: SlotType;
  position: number;
  section_instance_id?: string | null;
  section_id: string;
  claim_ids: string[];
  component_id: string;
  component_family: ComponentFamily;
  component_version: string;
  component_variant: "compact" | "standard" | "lead" | "mobile" | string;
  headline: string;
  dek?: string | null;
  display_fields: JsonRecord;
  hidden_detail_fields: JsonRecord;
  visual_priority: number;
  mobile_priority: number;
  generated_by: string;
  freshness_state: "current" | "aging" | string;
  trust: {
    claim_id?: string | null;
    claim_status?: string | null;
    claim_type?: string | null;
    confidence?: number | null;
    confidence_label?: string | null;
    epistemic_status?: string | null;
    source_label: string;
    evidence_count: number;
    counterevidence_count: number;
    snapshot_hash?: string | null;
  };
  times: {
    data_as_of?: string | null;
    assessed_at?: string | null;
    composed_at?: string | null;
    materially_updated_at?: string | null;
    expires_at?: string | null;
  };
  evidence_preview: {
    primary: unknown[];
    supporting: unknown[];
    counter: unknown[];
    source_coverage: JsonRecord;
    unresolved_questions: unknown[];
    known_limitations: unknown[];
  };
  topic?: {
    id: string;
    title: string;
    event_type: string;
    resolution_deadline_at: string;
  } | null;
  locale: LocaleState;
}

export interface PublicationSlot {
  id: string;
  type: SlotType;
  size: string;
  required: boolean;
  collapsible: boolean;
  desktop_order: number;
  mobile_order: number;
  items: RenderPlanItem[];
}

export interface PublicationClaimRecord {
  id: string;
  section_id: string;
  claim_type: string;
  statement: string;
  direction: "up" | "down" | "neutral" | string;
  change?: string | null;
  confidence?: number | null;
  confidence_label?: string | null;
  epistemic_status?: string | null;
  status: string;
  source_label: string;
  evidence_count: number;
  issued_at: string;
  updated_at: string;
  valid_until?: string | null;
}

export interface PublicationExpectationObservation {
  id: string;
  title: string;
  event_title?: string | null;
  event_key?: string | null;
  event_type: string;
  resolution_deadline_at: string;
  status: string;
  updated_at: string;
  source_market_count: number;
  source_market_status?: string | null;
  source_label: string;
  current_probability?: number | null;
  current_observed_at?: string | null;
  baseline_probability_24h?: number | null;
  baseline_observed_at?: string | null;
  delta_24h_percentage_points?: number | null;
  series: Array<[string, number]>;
  series_quality?: {
    coverage_status:
      | "complete"
      | "insufficient_observations"
      | "partial_window"
      | "stale_endpoint"
      | "gapped"
      | "no_material_variation"
      | string;
    requested_window_hours: number;
    observation_count: number;
    points_returned: number;
    first_observed_at?: string | null;
    last_observed_at?: string | null;
    span_hours: number;
    max_gap_hours: number;
    probability_range_percentage_points: number;
  };
}

export interface PublicationRuleObservation {
  id: string;
  title: string;
  rule_type: string;
  previous_state?: string | null;
  current_state: string;
  announced_at?: string | null;
  adopted_at?: string | null;
  effective_at?: string | null;
  enforcement_at?: string | null;
  updated_at: string;
  authority?: string | null;
  jurisdiction?: string | null;
  transition_at?: string | null;
  transition_confidence?: number | null;
  source_label: string;
}

export interface PublicationResearchWatch {
  id: string;
  candidate_type: string;
  headline: string;
  entity: string;
  topic_label: string;
  topic_ids: string[];
  metric: string;
  window_label: string;
  baseline_label: string;
  evidence_count: number;
  direction: "up" | "down" | "neutral" | string;
  screening_stage: "detected" | "investigated" | string;
  source_label: string;
  detected_at: string;
}

export interface PublicationSourceCoverage {
  source_slug: string;
  source_label: string;
  records_total: number;
  records_24h: number;
  latest_ingested_at?: string | null;
}

export interface PublicationContext {
  version: string;
  snapshot_bound: boolean;
  captured_at?: string | null;
  counts: {
    verified_claims: number;
    expectation_observations: number;
    rules_tracked: number;
    research_screening: number;
    source_records_24h: number;
  };
  claims: PublicationClaimRecord[];
  expectations: PublicationExpectationObservation[];
  rules: PublicationRuleObservation[];
  research: PublicationResearchWatch[];
  coverage: PublicationSourceCoverage[];
}

export interface FrontPageData {
  snapshot: {
    id: string;
    edition_date: string;
    composed_at: string;
    published_at: string;
    status: string;
    trigger_type: string;
    supersedes_edition_id?: string | null;
    previous_edition_id?: string | null;
    composer_version: string;
    policy_version: string;
    correction_count: number;
    is_current: boolean;
    publication_mode: "rolling_snapshot";
  };
  freshness: {
    state?: string;
    items?: Record<string, number>;
    sections?: Record<string, Record<string, number>>;
    retired_during_compile?: number;
    last_successful_compile_at: string;
    channel_updated_at?: string | null;
  };
  sections: string[];
  publication_context: PublicationContext;
  slots: PublicationSlot[];
  archive: Array<{
    id: string;
    edition_date: string;
    composed_at: string;
    status: string;
    sections: string[];
    claim_count: number;
    correction_count: number;
    trigger_type: string;
  }>;
  method: {
    summary: string;
    composer_version: string;
    policy_version: string;
  };
  system_state: {
    status: string;
    publication_channel: string;
    last_checked_at: string;
  };
  locale: LocaleState;
}

export interface FetchFrontPageResult {
  data: FrontPageData | null;
  etag: string | null;
  notModified: boolean;
}

export interface TopicPageData {
  topic: {
    id: string;
    title: string;
    event_type: string;
    outcome_type: string;
    resolution_deadline_at: string;
    resolution_authority?: string | null;
    resolution_rule_summary: string;
    status: string;
    canonicalization_version: string;
    created_at: string;
    updated_at: string;
  };
  source_event?: {
    id?: string | null;
    title?: string | null;
    slug?: string | null;
    tags: string[];
    source_url?: string | null;
  } | null;
  markets: Array<{
    id: string;
    external_market_id: string;
    question: string;
    description?: string | null;
    outcome_labels: string[];
    ends_at: string;
    liquidity?: number | null;
    volume?: number | null;
    status: string;
    current_probability?: number | null;
    current_observed_at?: string | null;
    baseline_probability_24h?: number | null;
    baseline_observed_at?: string | null;
    delta_24h_percentage_points?: number | null;
    source_url?: string | null;
    tags: string[];
  }>;
  signals: Array<{
    id: string;
    public_statement: string;
    claim_type: string;
    status: string;
    confidence?: number | null;
    confidence_label?: string | null;
    epistemic_status?: string | null;
    issued_at: string;
    updated_at: string;
  }>;
  method: { summary: string };
}

export interface SeoIndexData {
  claims: Array<{
    id: string;
    title: string;
    claim_type: string;
    desk_id: string;
    confidence_label?: string | null;
    epistemic_status?: string | null;
    status: string;
    published_at: string;
    updated_at: string;
    valid_until?: string | null;
  }>;
  topics: Array<{
    id: string;
    title: string;
    event_type: string;
    resolution_deadline_at: string;
    status: string;
    source_market_count: number;
    updated_at: string;
    current_probability?: number | null;
    current_observed_at?: string | null;
    delta_24h_percentage_points?: number | null;
    baseline_observed_at?: string | null;
  }>;
  editions: Array<{
    id: string;
    edition_date: string;
    updated_at: string;
    status: string;
    sections: string[];
    claim_count: number;
    correction_count: number;
    trigger_type: string;
  }>;
}

export interface EditionArchiveItem {
  id: string;
  edition_date: string;
  generated_at: string;
  status: string;
  sections: string[];
  claim_count: number;
  correction_count: number;
  trigger_type: string;
  first_published_at: string;
  record_class: "public_permanent" | "operational_ttl";
  payload_hash: string;
  event_count: number;
  latest_event_type?: string | null;
  latest_event_at?: string | null;
}

export interface EditionArchiveData {
  items: EditionArchiveItem[];
  next_cursor?: string | null;
  has_more: boolean;
  page_size: number;
  total_count: number;
  filters: {
    year?: number | null;
    section?: string | null;
    status?: string | null;
  };
  facets: {
    years: number[];
    sections: string[];
    statuses: string[];
  };
}

export interface EditionRecordData {
  id: string;
  edition_date: string;
  generated_at: string;
  status: string;
  first_published_at: string;
  record_class: "public_permanent";
  payload_hash: string;
  events: Array<{
    id: string;
    sequence_no: number;
    event_type: string;
    actor: string;
    reason?: string | null;
    related_edition_id?: string | null;
    previous_event_hash?: string | null;
    event_hash: string;
    created_at: string;
  }>;
}

export interface ExploreData {
  selection_version: string;
  ranking_as_of: string;
  topics: {
    items: ExploreEventGroup[];
    page: number;
    page_size: number;
    page_count: number;
    total_count: number;
    public_inventory_count: number;
    selected_group_count: number;
    represented_proposition_count: number;
    suppressed_proposition_count: number;
  };
  signals: {
    items: ExploreSignal[];
    page: number;
    page_size: number;
    page_count: number;
    total_count: number;
    public_record_count: number;
    current_record_count: number;
    current_subject_count: number;
    suppressed_snapshot_count: number;
  };
}

export interface ExploreEventGroup {
  key: string;
  title: string;
  event_type: string;
  external_event_id?: string | null;
  source_label: string;
  source_url?: string | null;
  source_member_count: number;
  eligible_member_count: number;
  suppressed_member_count: number;
  is_exclusive_slate: boolean;
  selection_reason: string;
  volume_24h: number;
  largest_move_24h_percentage_points?: number | null;
  latest_observed_at: string;
  resolution_deadline_at: string;
  members: Array<{
    topic_id: string;
    title: string;
    option_label?: string | null;
    event_type: string;
    current_probability?: number | null;
    baseline_probability_24h?: number | null;
    delta_24h_percentage_points?: number | null;
    observed_at?: string | null;
    resolution_deadline_at: string;
    selection_reason: string;
    recent_claim_id?: string | null;
  }>;
}

export interface ExploreSignal {
  id: string;
  title: string;
  claim_type: string;
  desk_id: string;
  section_id: string;
  confidence_label?: string | null;
  epistemic_status?: string | null;
  status: string;
  published_at: string;
  updated_at: string;
  valid_until?: string | null;
  subject_type?: string | null;
  subject_id?: string | null;
  event_key?: string | null;
  event_title?: string | null;
  topic_id?: string | null;
  selection_reason: string;
}

export async function fetchCurrentFrontPage(
  signal?: AbortSignal,
  etag?: string | null,
  locale = "en",
): Promise<FetchFrontPageResult> {
  const headers = new Headers();
  if (etag) headers.set("If-None-Match", etag);
  const response = await fetch(
    `/api/publication/current?locale=${encodeURIComponent(locale)}`,
    {
      cache: "no-store",
      headers,
      signal,
    },
  );
  if (response.status === 304) {
    return { data: null, etag: etag ?? null, notModified: true };
  }
  if (!response.ok) {
    throw new ApiError(`front page request failed (${response.status})`, response.status);
  }
  return {
    data: (await response.json()) as FrontPageData,
    etag: response.headers.get("ETag"),
    notModified: false,
  };
}

export async function fetchClaim(
  claimId: string,
  signal?: AbortSignal,
  locale = "en",
): Promise<ClaimPageData> {
  const response = await fetch(
    `/api/claims/${encodeURIComponent(claimId)}?locale=${encodeURIComponent(locale)}`,
    { cache: "no-store", signal },
  );
  if (!response.ok) {
    throw new ApiError(`claim request failed (${response.status})`, response.status);
  }
  return response.json() as Promise<ClaimPageData>;
}

// Compatibility types retained for downstream packages still on /editions/latest.
export interface CardData {
  id: string;
  headline: string;
  summary: string;
  trend: "up" | "down" | "neutral";
  probability?: number;
  confidence?: number;
  confidence_label?: string;
  source_label: string;
  section: string;
  tags: string[];
  issued_at: string | null;
}

export interface EditionData {
  id: string;
  edition_date: string;
  cards: CardData[];
}
