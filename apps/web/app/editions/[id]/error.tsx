"use client";

import Link from "next/link";
import { Icon } from "../../../components/icons";
import { SiteShell } from "../../../components/site-shell";

export default function EditionError({ reset }: { error: Error; reset: () => void }) {
  return (
    <SiteShell active="archive" systemState="unavailable">
      <div className="claim-route-state" role="alert">
        <p className="eyebrow">Archive temporarily unavailable</p>
        <h1>The immutable Edition could not be loaded.</h1>
        <p>No publication data was changed. Retry the read request or return to the current page.</p>
        <div><button onClick={reset} type="button"><Icon name="refresh" size={17} /> Retry</button><Link href="/">Current</Link></div>
      </div>
    </SiteShell>
  );
}
