from open_signal.orchestration.research import (
    _infer_openalex_topics,
    _metadata_topic_ids,
)


def test_transport_metadata_preserves_multiple_monitoring_topics() -> None:
    assert _metadata_topic_ids(
        {
            "monitoring_topics": {
                "synthetic-biology": True,
                "generative-ai": True,
                "quantum-computing": False,
            }
        }
    ) == ["generative-ai", "synthetic-biology"]


def test_legacy_openalex_record_is_inferred_only_from_frozen_concepts() -> None:
    payload = {
        "concepts": [
            {"display_name": "Large language models"},
            {"display_name": "CRISPR"},
        ]
    }
    topic_concepts = {
        "generative-ai": ["Large language models", "Artificial intelligence"],
        "synthetic-biology": ["CRISPR", "Synthetic biology"],
        "quantum-computing": ["Quantum computing"],
    }

    assert _infer_openalex_topics(payload, topic_concepts) == [
        "generative-ai",
        "synthetic-biology",
    ]
