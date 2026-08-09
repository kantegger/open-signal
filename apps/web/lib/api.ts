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
    status: string;
    desk_id: string;
    issued_at: string;
    valid_from?: string | null;
    valid_until?: string | null;
    materially_updated_at?: string | null;
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
