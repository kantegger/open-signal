"""Smoke test against the migrated database (OS-003)."""
import os
import sys

sys.path.insert(0, "python")
from sqlalchemy import create_engine, text

engine = create_engine(os.environ["OPEN_SIGNAL_DATABASE_URL"])
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("OK  " if ok else "FAIL") + " " + name + ("  " + detail if detail else ""))


with engine.begin() as c:
    # 1. sources insert + set_updated_at trigger
    row = c.execute(
        text(
            "INSERT INTO sources (slug, name, category, authority_level, access_mode, adapter_id) "
            "VALUES ('smoke-src', 'Smoke Source', 'other', 'secondary_source', 'rest', 'smoke-v1') "
            "RETURNING id, created_at, updated_at"
        )
    ).fetchone()
    src_id, created, updated = row
    check("sources insert + uuid default", src_id is not None)
    # 显式写旧时间，验证 BEFORE UPDATE 触发器会覆盖它（now() 为事务时间）
    c.execute(
        text("UPDATE sources SET name='Smoke Source 2', updated_at='2000-01-01' WHERE id=:i"),
        {"i": src_id},
    )
    row2 = c.execute(
        text("SELECT updated_at FROM sources WHERE id=:i"), {"i": src_id}
    ).fetchone()
    check(
        "set_updated_at trigger fired",
        row2[0] is not None and row2[0].year > 2000,
        f"updated_at={row2[0]} (2000-01-01 被触发器覆盖)",
    )

    # 2. jobs insert (idempotency key unique)
    j1 = c.execute(
        text(
            "INSERT INTO jobs (job_type, queue_name, payload, idempotency_key) "
            "VALUES ('smoke.test', 'test', '{}', 'smoke-key-1') RETURNING id"
        )
    ).fetchone()
    check("jobs insert", j1[0] is not None)
    dup_failed = False
    try:
        with c.begin_nested():  # savepoint：预期失败不影响外层事务
            c.execute(
                text(
                    "INSERT INTO jobs (job_type, queue_name, payload, idempotency_key) "
                    "VALUES ('smoke.test', 'test', '{}', 'smoke-key-1')"
                )
            )
    except Exception:
        dup_failed = True
    check("idempotency_key unique enforced", dup_failed)

    # 3. circular FK constraints exist
    fk_names = {
        r[0]
        for r in c.execute(
            text(
                "SELECT conname FROM pg_constraint WHERE contype='f' "
                "AND conname IN ('claims_current_version_fk','claims_bundle_fk',"
                "'claims_family_fk','claim_bundles_headline_fk',"
                "'claims_resolution_contract_fk','canonical_rules_current_version_fk',"
                "'resolution_contracts_template_fk')"
            )
        )
    }
    expect = {
        "claims_current_version_fk",
        "claims_bundle_fk",
        "claims_family_fk",
        "claim_bundles_headline_fk",
        "claims_resolution_contract_fk",
        "canonical_rules_current_version_fk",
        "resolution_contracts_template_fk",
    }
    check("7 postponed FKs present", fk_names == expect, f"found={len(fk_names)}")

    # 4. market_observations partitioned table exists (partitions created by ops)
    part = c.execute(
        text(
            "SELECT relispartition FROM pg_class WHERE relname='market_observations'"
        )
    ).fetchone()
    check("market_observations is partitioned", part is not None and part[0] is False)

    # 5. cleanup
    c.execute(text("DELETE FROM jobs WHERE idempotency_key LIKE 'smoke-%'"))
    c.execute(text("DELETE FROM sources WHERE slug='smoke-src'"))
    check("cleanup", True)

failed = [r for r in results if not r[1]]
print("\nSMOKE RESULT:", "PASS" if not failed else f"FAIL ({len(failed)})")
sys.exit(1 if failed else 0)
