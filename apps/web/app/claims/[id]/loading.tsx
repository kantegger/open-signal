import { SiteShell } from "../../../components/site-shell";

export default function ClaimLoading() {
  return (
    <SiteShell active="claim" systemState="checking">
      <div aria-busy="true" className="claim-record-page claim-loading">
        <div className="skeleton skeleton-kicker" />
        <div className="skeleton skeleton-headline" />
        <div className="skeleton skeleton-headline short" />
        <div className="skeleton-row"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div>
        <div className="skeleton skeleton-table" />
        <span className="sr-only">Loading Claim record.</span>
      </div>
    </SiteShell>
  );
}
