// Read-only API client for the public frontend (OS-030).
const API_BASE =
  process.env.OPEN_SIGNAL_API_URL ?? "http://localhost:8000";

export interface ClaimPageData {
  claim: {
    id: string;
    claim_type: string;
    public_statement: string;
    status: string;
    desk_id: string;
    issued_at: string;
  };
  observation: string;
  analysis: {
    structured_proposition: Record<string, unknown>;
    predicate?: string;
    operator?: string;
    value?: unknown;
  };
  assessment: {
    confidence?: number;
    confidence_label?: string;
    epistemic_status?: string;
    model_version?: string;
    charter_version?: string;
  };
  evidence: { items: unknown[]; snapshot_hash?: string };
  counterevidence: { items: unknown[]; snapshot_hash?: string };
  agent_lineage: {
    lineage_id: string;
    name?: string;
    foundation_model?: string;
    model_version?: string;
    charter_id?: string;
    status?: string;
  };
  version_history: Array<{
    version_number: number;
    public_statement: string;
    change_type: string;
    change_reason: string;
    confidence?: number;
    created_at: string;
  }>;
}

export async function fetchClaim(claimId: string): Promise<ClaimPageData> {
  const resp = await fetch(`${API_BASE}/api/claims/${claimId}`, {
    cache: "no-store",
  });
  if (!resp.ok) {
    throw new Error(`claim ${claimId} not found (${resp.status})`);
  }
  return resp.json();
}
