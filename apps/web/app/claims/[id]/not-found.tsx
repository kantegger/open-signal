import Link from "next/link";
import { SiteShell } from "../../../components/site-shell";

export default function ClaimNotFound() {
  return (
    <SiteShell active="explore">
      <div className="claim-route-state">
        <p className="eyebrow">Claim not found</p>
        <h1>No public record exists for this Claim identifier.</h1>
        <p>It may never have been published, or it may not be part of the public ledger.</p>
        <Link href="/">Return to the current front page →</Link>
      </div>
    </SiteShell>
  );
}
