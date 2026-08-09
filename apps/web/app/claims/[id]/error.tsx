"use client";

import Link from "next/link";
import { SiteShell } from "../../../components/site-shell";
import { Icon } from "../../../components/icons";

export default function ClaimError({ reset }: { error: Error; reset: () => void }) {
  return (
    <SiteShell active="claim" systemState="unavailable">
      <div className="claim-route-state" role="alert">
        <p className="eyebrow">Claim service unavailable</p>
        <h1>The permanent Claim record could not be loaded.</h1>
        <p>The ledger has not been changed. Retry the read request or return to the current snapshot.</p>
        <div><button onClick={reset} type="button"><Icon name="refresh" size={17} /> Retry</button><Link href="/">Current front page</Link></div>
      </div>
    </SiteShell>
  );
}
