"""Database metadata: 36 tables from spec appendix C.

SQLAlchemy Core ``Table`` objects mirror the appendix C DDL one-to-one:
- uuid / text[] / uuid[] / jsonb / interval map to PostgreSQL types
- circular foreign keys (claims <-> claim_versions, claims <->
  claim_bundles, claims <-> resolution_contracts) use ``use_alter=True``
  and are emitted as ALTER TABLE by the initial migration
- ``market_observations`` is range-partitioned by ``observed_at``
- ``vector(1536)`` uses a minimal UserDefinedType (pgvector-compatible)
"""

from __future__ import annotations

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Interval,
    MetaData,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import UserDefinedType

metadata = MetaData()

_tz = DateTime(timezone=True)


class Vector(UserDefinedType):
    """Minimal pgvector type. Dimension fixed at definition time."""

    cache_ok = True

    def __init__(self, dim: int = 1536) -> None:
        self.dim = dim

    def get_col_spec(self, **kwargs: object) -> str:
        return f"vector({self.dim})"


# ---------------------------------------------------------------- C.2
sources = Table(
    "sources",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("slug", Text, nullable=False, unique=True),
    Column("name", Text, nullable=False),
    Column("category", Text, nullable=False),
    Column("authority_level", Text, nullable=False),
    Column("access_mode", Text, nullable=False),
    Column("base_url", Text),
    Column("documentation_url", Text),
    Column("adapter_id", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="candidate"),
    Column("update_cadence", Interval),
    Column("last_successful_fetch_at", _tz),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
    Column("updated_at", _tz, nullable=False, server_default=text("now()")),
)

rights_manifests = Table(
    "rights_manifests",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("source_id", Uuid(), ForeignKey("sources.id"), nullable=False),
    Column("access_basis", Text, nullable=False),
    Column("license_name", Text),
    Column("license_url", Text),
    Column("allowed_operations", JSONB, nullable=False, server_default="{}"),
    Column("attribution_required", Boolean, nullable=False, server_default="false"),
    Column("attribution_format", Text),
    Column("maximum_retention_days", Integer),
    Column("excerpt_character_limit", Integer),
    Column("territorial_restrictions", ARRAY(Text), nullable=False, server_default="{}"),
    Column("additional_conditions", ARRAY(Text), nullable=False, server_default="{}"),
    Column("reviewed_at", _tz, nullable=False),
    Column("reviewed_by", Text, nullable=False),
    Column("source_document_hash", Text),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
)

# ---------------------------------------------------------------- C.3
raw_source_records = Table(
    "raw_source_records",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("source_id", Uuid(), ForeignKey("sources.id"), nullable=False),
    Column("external_id", Text, nullable=False),
    Column("external_parent_id", Text),
    Column("record_type", Text, nullable=False),
    Column("mime_type", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("source_created_at", _tz),
    Column("source_updated_at", _tz),
    Column("first_seen_at", _tz, nullable=False, server_default=text("now()")),
    Column("last_seen_at", _tz, nullable=False, server_default=text("now()")),
    Column("ingested_at", _tz, nullable=False, server_default=text("now()")),
    Column("content_hash", Text, nullable=False),
    Column("transport_metadata", JSONB, nullable=False, server_default="{}"),
    Column("rights_manifest_id", Uuid(), ForeignKey("rights_manifests.id")),
    Column("adapter_version", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="active"),
    UniqueConstraint("source_id", "external_id", "content_hash"),
    Index("raw_source_records_source_external_idx", "source_id", "external_id"),
    Index("raw_source_records_updated_idx", "source_updated_at", postgresql_ops={"source_updated_at": "DESC"}),
)

raw_artifacts = Table(
    "raw_artifacts",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("source_id", Uuid(), ForeignKey("sources.id"), nullable=False),
    Column("raw_source_record_id", Uuid(), ForeignKey("raw_source_records.id")),
    Column("artifact_type", Text, nullable=False),
    Column("storage_key", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("byte_size", BigInteger, nullable=False),
    Column("fetched_at", _tz, nullable=False),
    Column("source_url", Text, nullable=False),
    Column("rights_manifest_id", Uuid(), ForeignKey("rights_manifests.id")),
    Column("retention_policy_id", Text),
    UniqueConstraint("content_hash", "artifact_type"),
)

# ---------------------------------------------------------------- C.4
canonical_entities = Table(
    "canonical_entities",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("entity_type", Text, nullable=False),
    Column("canonical_name", Text, nullable=False),
    Column("aliases", ARRAY(Text), nullable=False, server_default="{}"),
    Column("identifiers", JSONB, nullable=False, server_default="[]"),
    Column("status", Text, nullable=False, server_default="active"),
    Column("merged_into_id", Uuid(), ForeignKey("canonical_entities.id")),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
    Column("updated_at", _tz, nullable=False, server_default=text("now()")),
    Index(
        "canonical_entities_name_idx",
        text("to_tsvector('simple', canonical_name)"),
        postgresql_using="gin",
    ),
)

source_entity_mappings = Table(
    "source_entity_mappings",
    metadata,
    Column("source_id", Uuid(), ForeignKey("sources.id"), primary_key=True),
    Column("external_entity_id", Text, primary_key=True),
    Column("canonical_entity_id", Uuid(), ForeignKey("canonical_entities.id"), nullable=False),
    Column("mapping_type", Text, nullable=False),
    Column("confidence", Numeric(5, 4), nullable=False),
    Column("evidence", JSONB, nullable=False, server_default="[]"),
    Column("mapper_version", Text, nullable=False),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
)

# ---------------------------------------------------------------- C.5
source_markets = Table(
    "source_markets",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("source_id", Uuid(), ForeignKey("sources.id"), nullable=False),
    Column("external_market_id", Text, nullable=False),
    Column("external_event_id", Text),
    Column("question", Text, nullable=False),
    Column("description", Text),
    Column("outcome_labels", ARRAY(Text), nullable=False),
    Column("token_ids", ARRAY(Text), nullable=False, server_default="{}"),
    Column("starts_at", _tz),
    Column("ends_at", _tz, nullable=False),
    Column("rules_text", Text),
    Column("rules_hash", Text),
    Column("liquidity", Numeric),
    Column("volume", Numeric),
    Column("status", Text, nullable=False),
    Column("raw_source_record_id", Uuid(), ForeignKey("raw_source_records.id")),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
    Column("updated_at", _tz, nullable=False, server_default=text("now()")),
    UniqueConstraint("source_id", "external_market_id"),
)

canonical_expectations = Table(
    "canonical_expectations",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("canonical_question", Text, nullable=False),
    Column("subject_entity_ids", ARRAY(Uuid()), nullable=False, server_default="{}"),
    Column("event_type", Text, nullable=False),
    Column("outcome_type", Text, nullable=False),
    Column("threshold", Numeric),
    Column("threshold_unit", Text),
    Column("observation_start_at", _tz),
    Column("resolution_deadline_at", _tz, nullable=False),
    Column("resolution_authority", Text),
    Column("resolution_rule_summary", Text, nullable=False),
    Column("resolution_rule_hash", Text, nullable=False),
    Column("source_market_ids", ARRAY(Uuid()), nullable=False),
    Column("status", Text, nullable=False, server_default="active"),
    Column("canonicalization_version", Text, nullable=False),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
    Column("updated_at", _tz, nullable=False, server_default=text("now()")),
)

market_observations = Table(
    "market_observations",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("source_market_id", Uuid(), ForeignKey("source_markets.id"), nullable=False),
    Column("observed_at", _tz, nullable=False, primary_key=True),
    Column("probability", Numeric(7, 6)),
    Column("best_bid", Numeric(7, 6)),
    Column("best_ask", Numeric(7, 6)),
    Column("midpoint", Numeric(7, 6)),
    Column("last_trade_price", Numeric(7, 6)),
    Column("spread", Numeric(7, 6)),
    Column("volume", Numeric),
    Column("open_interest", Numeric),
    Column("price_method", Text, nullable=False),
    Column("data_quality_flags", ARRAY(Text), nullable=False, server_default="{}"),
    Column("raw_source_record_id", Uuid(), ForeignKey("raw_source_records.id")),
    Index(
        "market_observations_market_time_idx",
        "source_market_id",
        "observed_at",
        postgresql_ops={"observed_at": "DESC"},
    ),
    postgresql_partition_by="RANGE (observed_at)",
)

# ---------------------------------------------------------------- C.6
canonical_rules = Table(
    "canonical_rules",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("title", Text, nullable=False),
    Column("jurisdiction_id", Uuid(), ForeignKey("canonical_entities.id")),
    Column("issuing_authority_id", Uuid(), ForeignKey("canonical_entities.id")),
    Column("rule_type", Text, nullable=False),
    Column("current_state", Text, nullable=False),
    Column("previous_state", Text),
    Column("official_identifier", Text),
    Column("docket_identifiers", ARRAY(Text), nullable=False, server_default="{}"),
    Column("announced_at", _tz),
    Column("adopted_at", _tz),
    Column("signed_at", _tz),
    Column("effective_at", _tz),
    Column("enforcement_at", _tz),
    Column("affected_entity_type_ids", ARRAY(Text), nullable=False, server_default="{}"),
    Column("topic_ids", ARRAY(Uuid()), nullable=False, server_default="{}"),
    Column("current_version_id", Uuid()),
    Column("status", Text, nullable=False, server_default="active"),
    Column("ontology_version", Text, nullable=False),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
    Column("updated_at", _tz, nullable=False, server_default=text("now()")),
)

rule_versions = Table(
    "rule_versions",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("canonical_rule_id", Uuid(), ForeignKey("canonical_rules.id"), nullable=False),
    Column("version_label", Text, nullable=False),
    Column("document_date", Date, nullable=False),
    Column("source_document_ids", ARRAY(Uuid()), nullable=False),
    Column("authoritative_artifact_id", Uuid(), ForeignKey("raw_artifacts.id")),
    Column("text_hash", Text, nullable=False),
    Column("structure_hash", Text),
    Column("state_at_version", Text, nullable=False),
    Column("effective_at", _tz),
    Column("supersedes_version_id", Uuid(), ForeignKey("rule_versions.id")),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
)

rule_transitions = Table(
    "rule_transitions",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("canonical_rule_id", Uuid(), ForeignKey("canonical_rules.id"), nullable=False),
    Column("from_state", Text, nullable=False),
    Column("to_state", Text, nullable=False),
    Column("occurred_at", _tz, nullable=False),
    Column("detected_at", _tz, nullable=False, server_default=text("now()")),
    Column("authoritative_source_record_ids", ARRAY(Uuid()), nullable=False),
    Column("transition_confidence", Numeric(5, 4), nullable=False),
    Column("mapping_version", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="candidate"),
    UniqueConstraint("canonical_rule_id", "from_state", "to_state", "occurred_at"),
)

# ---------------------------------------------------------------- C.7
research_topics = Table(
    "research_topics",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("taxonomy_source", Text, nullable=False),
    Column("external_topic_id", Text),
    Column("parent_topic_ids", ARRAY(Uuid()), nullable=False, server_default="{}"),
    Column("alias_terms", ARRAY(Text), nullable=False, server_default="{}"),
    Column("definition_version", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="active"),
    Column("embedding", Vector(1536)),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
    Column("updated_at", _tz, nullable=False, server_default=text("now()")),
)

research_works = Table(
    "research_works",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("title", Text, nullable=False),
    Column("publication_date", Date),
    Column("work_type", Text, nullable=False),
    Column("doi", Text),
    Column("external_ids", JSONB, nullable=False, server_default="[]"),
    Column("author_entity_ids", ARRAY(Uuid()), nullable=False, server_default="{}"),
    Column("institution_entity_ids", ARRAY(Uuid()), nullable=False, server_default="{}"),
    Column("topic_ids", ARRAY(Uuid()), nullable=False, server_default="{}"),
    Column("abstract_text", Text),
    Column("abstract_rights", Text),
    Column("open_access_locations", ARRAY(Text), nullable=False, server_default="{}"),
    Column("source_record_ids", ARRAY(Uuid()), nullable=False),
    Column("status", Text, nullable=False, server_default="active"),
    Column("title_embedding", Vector(1536)),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
    Column("updated_at", _tz, nullable=False, server_default=text("now()")),
    Index(
        "research_works_doi_idx",
        text("lower(doi)"),
        unique=True,
        postgresql_where=text("doi IS NOT NULL"),
    ),
)

research_relations = Table(
    "research_relations",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("left_object_id", Uuid(), nullable=False),
    Column("right_object_id", Uuid(), nullable=False),
    Column("relation_type", Text, nullable=False),
    Column("observed_at", _tz),
    Column("strength", Numeric),
    Column("measurement_method", Text),
    Column("source_record_ids", ARRAY(Uuid()), nullable=False, server_default="{}"),
    Column("status", Text, nullable=False),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
)

research_signal_candidates = Table(
    "research_signal_candidates",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("candidate_type", Text, nullable=False),
    Column("subject_ids", ARRAY(Uuid()), nullable=False),
    Column("observation_window_start", _tz, nullable=False),
    Column("observation_window_end", _tz, nullable=False),
    Column("baseline_definition", Text, nullable=False),
    Column("derived_metrics", JSONB, nullable=False, server_default="{}"),
    Column("evidence_relation_ids", ARRAY(Uuid()), nullable=False, server_default="{}"),
    Column("candidate_generator_version", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="generated"),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
)

# ---------------------------------------------------------------- C.8
agent_desks = Table(
    "agent_desks",
    metadata,
    Column("id", Text, primary_key=True),
    Column("title", Text, nullable=False),
    Column("editorial_mission", Text, nullable=False),
    Column("charter_version", Text, nullable=False),
    Column("maturity", Text, nullable=False),
    Column("public_track_record_enabled", Boolean, nullable=False, server_default="false"),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
)

agent_lineages = Table(
    "agent_lineages",
    metadata,
    Column("id", Text, primary_key=True),
    Column("desk_id", Text, ForeignKey("agent_desks.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("foundation_model", Text, nullable=False),
    Column("model_version", Text, nullable=False),
    Column("charter_id", Text, nullable=False),
    Column("charter_version", Text, nullable=False),
    Column("toolset_version", Text, nullable=False),
    Column("context_builder_version", Text, nullable=False),
    Column("parent_lineage_id", Text, ForeignKey("agent_lineages.id")),
    Column("status", Text, nullable=False),
    Column("activated_at", _tz),
    Column("retired_at", _tz),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
)

investigation_runs = Table(
    "investigation_runs",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("desk_id", Text, ForeignKey("agent_desks.id"), nullable=False),
    Column("section_id", Text, nullable=False),
    Column("capability_id", Text, nullable=False),
    Column("candidate_id", Uuid()),
    Column("agent_lineage_id", Text, ForeignKey("agent_lineages.id"), nullable=False),
    Column("model_version", Text, nullable=False),
    Column("charter_version", Text, nullable=False),
    Column("started_at", _tz, nullable=False, server_default=text("now()")),
    Column("completed_at", _tz),
    Column("status", Text, nullable=False),
    Column("input_snapshot_id", Uuid()),
    Column("total_input_tokens", Integer),
    Column("total_output_tokens", Integer),
    Column("total_tool_calls", Integer),
    Column("estimated_cost_usd", Numeric(12, 6)),
    Column("output_judgment", JSONB),
    Column("error_details", JSONB),
)

evidence_bundles = Table(
    "evidence_bundles",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("primary_evidence", JSONB, nullable=False, server_default="[]"),
    Column("supporting_evidence", JSONB, nullable=False, server_default="[]"),
    Column("counter_evidence", JSONB, nullable=False, server_default="[]"),
    Column("data_calculation_ids", ARRAY(Uuid()), nullable=False, server_default="{}"),
    Column("source_coverage", JSONB, nullable=False, server_default="{}"),
    Column("unresolved_questions", ARRAY(Text), nullable=False, server_default="{}"),
    Column("known_limitations", ARRAY(Text), nullable=False, server_default="{}"),
    Column("snapshot_hash", Text, nullable=False),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
)

# ---------------------------------------------------------------- C.9
claim_families = Table(
    "claim_families",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("family_key", Text, nullable=False, unique=True),
    Column("head_claim_id", Uuid()),
    Column("description", Text),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
)

claim_bundles = Table(
    "claim_bundles",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("section_instance_id", Uuid(), nullable=False),
    Column("section_id", Text, nullable=False),
    Column("desk_id", Text, ForeignKey("agent_desks.id"), nullable=False),
    Column("headline_claim_id", Uuid()),
    Column("status", Text, nullable=False, server_default="draft"),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
)

claims = Table(
    "claims",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("institution_id", Text, nullable=False, server_default="open-signal"),
    Column("desk_id", Text, ForeignKey("agent_desks.id"), nullable=False),
    Column("agent_lineage_id", Text, ForeignKey("agent_lineages.id"), nullable=False),
    Column("model_version", Text, nullable=False),
    Column("charter_version", Text, nullable=False),
    Column("run_id", Uuid(), ForeignKey("investigation_runs.id"), nullable=False),
    Column("section_id", Text, nullable=False),
    Column("capability_id", Text, nullable=False),
    Column("claim_type", Text, nullable=False),
    Column("claim_family_id", Uuid()),
    Column("bundle_id", Uuid()),
    Column("public_statement", Text, nullable=False),
    Column("structured_proposition", JSONB, nullable=False),
    Column("confidence", Numeric(5, 4)),
    Column("confidence_label", Text),
    Column("epistemic_status", Text, nullable=False),
    Column("evidence_bundle_id", Uuid(), ForeignKey("evidence_bundles.id"), nullable=False),
    Column("evidence_snapshot_hash", Text, nullable=False),
    Column("issued_at", _tz, nullable=False),
    Column("valid_from", _tz),
    Column("valid_until", _tz),
    Column("resolution_contract_id", Uuid()),
    Column("status", Text, nullable=False, server_default="draft"),
    Column("current_version_id", Uuid()),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
    Column("updated_at", _tz, nullable=False, server_default=text("now()")),
)

claim_versions = Table(
    "claim_versions",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("claim_id", Uuid(), ForeignKey("claims.id"), nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("public_statement", Text, nullable=False),
    Column("structured_proposition", JSONB, nullable=False),
    Column("confidence", Numeric(5, 4)),
    Column("evidence_bundle_id", Uuid(), ForeignKey("evidence_bundles.id"), nullable=False),
    Column("change_type", Text, nullable=False),
    Column("change_reason", Text, nullable=False),
    Column("previous_version_id", Uuid(), ForeignKey("claim_versions.id")),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
    Column("created_by_run_id", Uuid(), ForeignKey("investigation_runs.id")),
    UniqueConstraint("claim_id", "version_number"),
)

claim_events = Table(
    "claim_events",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("claim_id", Uuid(), ForeignKey("claims.id"), nullable=False),
    Column("event_type", Text, nullable=False),
    Column("payload", JSONB, nullable=False, server_default="{}"),
    Column("occurred_at", _tz, nullable=False, server_default=text("now()")),
    Column("actor_type", Text, nullable=False),
    Column("actor_id", Text, nullable=False),
    Column("previous_event_hash", Text),
    Column("current_event_hash", Text, nullable=False),
    Index("claim_events_claim_time_idx", "claim_id", "occurred_at"),
)

claim_relations = Table(
    "claim_relations",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("source_claim_id", Uuid(), ForeignKey("claims.id"), nullable=False),
    Column("target_claim_id", Uuid(), ForeignKey("claims.id"), nullable=False),
    Column("relation_type", Text, nullable=False),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
    UniqueConstraint("source_claim_id", "target_claim_id", "relation_type"),
)

claim_evidence = Table(
    "claim_evidence",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("claim_id", Uuid(), ForeignKey("claims.id"), nullable=False),
    Column("evidence_bundle_id", Uuid(), ForeignKey("evidence_bundles.id"), nullable=False),
    Column("evidence_item_key", Text, nullable=False),
    Column("role", Text, nullable=False),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
)

# ---------------------------------------------------------------- C.11
resolution_templates = Table(
    "resolution_templates",
    metadata,
    Column("id", Text, primary_key=True),
    Column("version", Text, primary_key=True),
    Column("claim_type", Text, nullable=False),
    Column("section_ids", ARRAY(Text), nullable=False),
    Column("description", Text, nullable=False),
    Column("required_proposition_fields", ARRAY(Text), nullable=False),
    Column("default_evaluation_window", Interval),
    Column("scoring_rule_id", Text, nullable=False),
    Column("partial_credit_allowed", Boolean, nullable=False),
    Column("maturity", Text, nullable=False),
    Column("activated_at", _tz, nullable=False),
)

resolution_contracts = Table(
    "resolution_contracts",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("claim_id", Uuid(), ForeignKey("claims.id"), nullable=False, unique=True),
    Column("template_id", Text, nullable=False),
    Column("template_version", Text, nullable=False),
    Column("issued_at", _tz, nullable=False),
    Column("evaluation_start_at", _tz, nullable=False),
    Column("evaluation_deadline", _tz, nullable=False),
    Column("resolution_predicate", JSONB, nullable=False),
    Column("resolution_source_ids", ARRAY(Uuid()), nullable=False),
    Column("scoring_rule_id", Text, nullable=False),
    Column("partial_credit_policy", Text),
    Column("ambiguity_policy", Text, nullable=False),
    Column("missing_data_policy", Text, nullable=False),
    Column("locked_at", _tz, nullable=False),
    Column("lock_hash", Text, nullable=False),
    Column("status", Text, nullable=False),
)

resolution_records = Table(
    "resolution_records",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("claim_id", Uuid(), ForeignKey("claims.id"), nullable=False),
    Column("resolution_contract_id", Uuid(), ForeignKey("resolution_contracts.id"), nullable=False),
    Column("outcome", Text, nullable=False),
    Column("numeric_outcome", Numeric),
    Column("component_scores", JSONB),
    Column("final_score", Numeric),
    Column("resolution_source_record_ids", ARRAY(Uuid()), nullable=False),
    Column("calculation_record_ids", ARRAY(Uuid()), nullable=False, server_default="{}"),
    Column("resolver_run_ids", ARRAY(Uuid()), nullable=False, server_default="{}"),
    Column("resolved_at", _tz, nullable=False),
    Column("status", Text, nullable=False),
    Column("resolution_version", Text, nullable=False),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
)

calibration_records = Table(
    "calibration_records",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("desk_id", Text, ForeignKey("agent_desks.id"), nullable=False),
    Column("period_start", _tz, nullable=False),
    Column("period_end", _tz, nullable=False),
    Column("bucket_low", Numeric, nullable=False),
    Column("bucket_high", Numeric, nullable=False),
    Column("bucket_size", Integer, nullable=False),
    Column("empirical_rate", Numeric, nullable=False),
    Column("expected_rate", Numeric, nullable=False),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
)

desk_scorecards = Table(
    "desk_scorecards",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("desk_id", Text, ForeignKey("agent_desks.id"), nullable=False),
    Column("period_start", _tz, nullable=False),
    Column("period_end", _tz, nullable=False),
    Column("metrics", JSONB, nullable=False),
    Column("scorecard_version", Text, nullable=False),
    Column("generated_at", _tz, nullable=False, server_default=text("now()")),
)

autonomy_policies = Table(
    "autonomy_policies",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("version", Text, nullable=False),
    Column("applicable_desk_ids", ARRAY(Text), nullable=False),
    Column("applicable_capability_ids", ARRAY(Text), nullable=False),
    Column("policy", JSONB, nullable=False),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
    UniqueConstraint("id", "version"),
)

# ---------------------------------------------------------------- C.12
daily_editions = Table(
    "daily_editions",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("edition_date", Date, nullable=False),
    Column("generated_at", _tz, nullable=False),
    Column("status", Text, nullable=False),
    Column("included_section_ids", ARRAY(Text), nullable=False),
    Column("included_claim_ids", ARRAY(Uuid()), nullable=False),
    Column("composer_version", Text, nullable=False),
    Column("component_versions", JSONB, nullable=False),
    Column("generation_cost_usd", Numeric(12, 6), nullable=False, server_default="0"),
    Column("correction_count", Integer, nullable=False, server_default="0"),
    Column("edition_payload", JSONB, nullable=False),
    UniqueConstraint("edition_date", "generated_at"),
)

render_plans = Table(
    "render_plans",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("edition_id", Uuid(), ForeignKey("daily_editions.id"), nullable=False),
    Column("slot_id", Text, nullable=False),
    Column("section_instance_id", Uuid()),
    Column("claim_ids", ARRAY(Uuid()), nullable=False),
    Column("component_id", Text, nullable=False),
    Column("component_version", Text, nullable=False),
    Column("component_variant", Text, nullable=False),
    Column("headline", Text, nullable=False),
    Column("dek", Text),
    Column("display_fields", JSONB, nullable=False),
    Column("hidden_detail_fields", JSONB, nullable=False, server_default="{}"),
    Column("evidence_bundle_id", Uuid(), ForeignKey("evidence_bundles.id")),
    Column("visual_priority", Integer, nullable=False),
    Column("mobile_priority", Integer, nullable=False),
    Column("generated_by", Text, nullable=False),
    Column("approved_by_verification_run_id", Uuid(), ForeignKey("investigation_runs.id")),
)

jobs = Table(
    "jobs",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("job_type", Text, nullable=False),
    Column("queue_name", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("priority", Integer, nullable=False, server_default="100"),
    Column("run_after", _tz, nullable=False, server_default=text("now()")),
    Column("status", Text, nullable=False, server_default="queued"),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("maximum_attempts", Integer, nullable=False, server_default="5"),
    Column("locked_by", Text),
    Column("locked_at", _tz),
    Column("idempotency_key", Text, nullable=False, unique=True),
    Column("created_at", _tz, nullable=False, server_default=text("now()")),
    Column("completed_at", _tz),
    Index("jobs_claim_idx", "queue_name", "status", "run_after", "priority"),
)

# spec §93 Source Cursor (appendix C did not include this table; added by OS-007)
source_cursors = Table(
    "source_cursors",
    metadata,
    Column("source_id", Text, ForeignKey("sources.id"), primary_key=True),
    Column("cursor_type", Text, nullable=False),
    Column("value", Text, nullable=False),
    Column("last_successful_fetch_at", _tz, nullable=False, server_default=text("now()")),
    Column("last_seen_source_timestamp", _tz),
    Column("adapter_version", Text, nullable=False),
    Column("updated_at", _tz, nullable=False, server_default=text("now()")),
)

# Calculation records (OS-010; appendix C omitted this table — evidence_bundles
# and resolution_records reference calculation_record_ids)
calculation_records = Table(
    "calculation_records",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default="gen_random_uuid()"),
    Column("calculation_type", Text, nullable=False),
    Column("subject_id", Uuid()),
    Column("subject_type", Text, nullable=False),
    Column("input_snapshot", JSONB, nullable=False, server_default="{}"),
    Column("output", JSONB, nullable=False),
    Column("calculation_version", Text, nullable=False),
    Column("calculated_at", _tz, nullable=False, server_default=text("now()")),
)


# Circular foreign keys emitted as ALTER TABLE by the initial migration.
def _postponed_fks() -> None:
    from sqlalchemy import ForeignKeyConstraint

    constraints: list[ForeignKeyConstraint] = [
        ForeignKeyConstraint(
            ["current_version_id"],
            ["claim_versions.id"],
            name="claims_current_version_fk",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["bundle_id"],
            ["claim_bundles.id"],
            name="claims_bundle_fk",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["claim_family_id"],
            ["claim_families.id"],
            name="claims_family_fk",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["resolution_contract_id"],
            ["resolution_contracts.id"],
            name="claims_resolution_contract_fk",
            use_alter=True,
        ),
    ]
    for table in (claims, claim_bundles):
        if table.name == "claims":
            for c in constraints:
                table.append_constraint(c)
        else:
            table.append_constraint(
                ForeignKeyConstraint(
                    ["headline_claim_id"],
                    ["claims.id"],
                    name="claim_bundles_headline_fk",
                    use_alter=True,
                )
            )
    # canonical_rules.current_version_id -> rule_versions.id
    canonical_rules.append_constraint(
        ForeignKeyConstraint(
            ["current_version_id"],
            ["rule_versions.id"],
            name="canonical_rules_current_version_fk",
            use_alter=True,
        )
    )
    # resolution_contracts (template_id, template_version) -> resolution_templates
    resolution_contracts.append_constraint(
        ForeignKeyConstraint(
            ["template_id", "template_version"],
            ["resolution_templates.id", "resolution_templates.version"],
            name="resolution_contracts_template_fk",
            use_alter=True,
        )
    )


_postponed_fks()
