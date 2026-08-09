import { SiteShell } from "../../../components/site-shell";

export default function TopicLoading() {
  return (
    <SiteShell active="explore" systemState="checking">
      <div aria-busy="true" className="topic-page skeleton-page">
        <div className="skeleton skeleton-kicker" />
        <div className="skeleton skeleton-headline" />
        <div className="skeleton skeleton-chart" />
        <span className="sr-only">Loading expectation topic.</span>
      </div>
    </SiteShell>
  );
}
