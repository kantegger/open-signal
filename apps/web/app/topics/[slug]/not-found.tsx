import Link from "next/link";
import { SiteShell } from "../../../components/site-shell";

export default function TopicNotFound() {
  return (
    <SiteShell active="explore">
      <div className="claim-route-state">
        <p className="eyebrow">Topic not found</p>
        <h1>No public canonical expectation exists for this identifier.</h1>
        <Link href="/">Return to the current front page →</Link>
      </div>
    </SiteShell>
  );
}
