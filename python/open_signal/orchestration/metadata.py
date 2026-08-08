"""Idempotent runtime metadata seeding from machine-readable definitions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from open_signal.sources.registry import Registry

SOURCE_DEFINITIONS = (
    (
        "polymarket-gamma",
        "Polymarket Gamma",
        "prediction_market",
        "licensed_aggregator",
        "rest",
        "polymarket-gamma-v1",
    ),
    (
        "federal-register",
        "Federal Register",
        "government_regulation",
        "official_government",
        "rest",
        "federal-register-v1",
    ),
    (
        "openalex",
        "OpenAlex",
        "scholarly_metadata",
        "open_aggregator",
        "rest",
        "openalex-v1",
    ),
    (
        "clinicaltrials-gov",
        "ClinicalTrials.gov",
        "clinical_registry",
        "official_government",
        "rest",
        "clinicaltrials-v1",
    ),
)


def ensure_runtime_metadata(engine: Any) -> dict[str, str]:
    """Ensure Registry desks and launch source identities exist."""
    Registry.load().sync_desks(engine)
    with engine.begin() as conn:
        for slug, name, category, authority, access, adapter in SOURCE_DEFINITIONS:
            conn.execute(
                text(
                    """
                    INSERT INTO sources
                      (slug, name, category, authority_level, access_mode,
                       adapter_id, status)
                    VALUES
                      (:slug, :name, :category, :authority, :access,
                       :adapter, 'active')
                    ON CONFLICT (slug) DO NOTHING
                    """
                ),
                {
                    "slug": slug,
                    "name": name,
                    "category": category,
                    "authority": authority,
                    "access": access,
                    "adapter": adapter,
                },
            )
        rows = conn.execute(
            text(
                "SELECT slug, id FROM sources "
                "WHERE slug = ANY(:slugs)"
            ),
            {"slugs": [item[0] for item in SOURCE_DEFINITIONS]},
        ).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}
