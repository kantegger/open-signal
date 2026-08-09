import { SiteShell } from "../components/site-shell";

export default function Loading() {
  return (
    <SiteShell systemState="checking">
      <div aria-busy="true" className="front-page skeleton-page">
        <div className="skeleton skeleton-title" />
        <div className="skeleton skeleton-kicker" />
        <div className="skeleton skeleton-headline" />
        <div className="skeleton skeleton-headline short" />
        <div className="skeleton skeleton-chart" />
        <span className="sr-only">Loading the latest verified snapshot.</span>
      </div>
    </SiteShell>
  );
}
