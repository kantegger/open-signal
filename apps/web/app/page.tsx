"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

interface Edition {
  id: string;
  edition_date: string;
  edition_payload: { title?: string };
  sections: string[];
  claim_ids: string[];
  generated_at: string;
}

export default function HomePage() {
  const [edition, setEdition] = useState<Edition | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("http://localhost:8000/api/editions/latest")
      .then((r) => (r.ok ? r.json() : null))
      .then(setEdition)
      .catch((e) => setError(e.message));
  }, []);

  if (error)
    return <p style={{ padding: "2rem" }}>API offline — start uvicorn on :8000</p>;
  if (!edition)
    return <p style={{ padding: "2rem" }}>Loading...</p>;

  return (
    <main style={{ maxWidth: 720, margin: "2rem auto", fontFamily: "system-ui" }}>
      <h1>{edition.edition_payload?.title ?? "Open Signal"}</h1>
      <p style={{ color: "#666" }}>{edition.edition_date}</p>

      <h2>Sections</h2>
      <ul>{edition.sections.map((s) => <li key={s}>{s}</li>)}</ul>

      <h2>Claims</h2>
      {edition.claim_ids.length === 0 ? (
        <p>No claims published yet.</p>
      ) : (
        <ul>
          {edition.claim_ids.map((cid) => (
            <li key={cid} style={{ marginBottom: ".5rem" }}>
              <Link href={`/claims/${cid}`}>{cid.slice(0, 8)}...</Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
