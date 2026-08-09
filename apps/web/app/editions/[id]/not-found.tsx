import Link from "next/link";
import { SiteShell } from "../../../components/site-shell";

export default function EditionNotFound() {
  return (
    <SiteShell active="archive">
      <div className="claim-route-state">
        <p className="eyebrow">Edition not found</p>
        <h1>No public snapshot exists for this Edition identifier.</h1>
        <p>The current publication and all indexed archive snapshots remain available.</p>
        <Link href="/#archive">Return to the archive →</Link>
      </div>
    </SiteShell>
  );
}
