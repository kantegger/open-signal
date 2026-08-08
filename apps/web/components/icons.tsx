import type { SVGProps } from "react";

export type IconName =
  | "pulse"
  | "trend"
  | "document"
  | "search"
  | "method"
  | "archive"
  | "evidence"
  | "arrow"
  | "close"
  | "menu"
  | "lock"
  | "refresh";

const paths: Record<IconName, React.ReactNode> = {
  pulse: <path d="M2 12h4l2.3-7 4.1 14 2.5-8H22" />,
  trend: <><path d="m3 17 6-6 4 4 8-9" /><path d="M15 6h6v6" /></>,
  document: <><path d="M5 2h10l4 4v16H5z" /><path d="M15 2v5h5M8 12h8M8 16h8" /></>,
  search: <><circle cx="10.5" cy="10.5" r="7.5" /><path d="m16 16 5 5" /></>,
  method: <><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M4.9 4.9 7 7M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1 7 17M17 7l2.1-2.1" /></>,
  archive: <><path d="M3 7h18v14H3zM2 3h20v4H2z" /><path d="M9 11h6" /></>,
  evidence: <><path d="M5 2h10l4 4v16H5z" /><path d="M15 2v5h5M8 12h8M8 16h5" /></>,
  arrow: <><path d="M5 12h14" /><path d="m14 7 5 5-5 5" /></>,
  close: <><path d="m5 5 14 14M19 5 5 19" /></>,
  menu: <><path d="M3 6h18M3 12h18M3 18h18" /></>,
  lock: <><rect x="5" y="10" width="14" height="11" rx="1" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></>,
  refresh: <><path d="M20 7v5h-5" /><path d="M19 12a7 7 0 1 0-2 5" /></>,
};

export function Icon({
  name,
  size = 24,
  ...props
}: SVGProps<SVGSVGElement> & { name: IconName; size?: number }) {
  return (
    <svg
      aria-hidden="true"
      fill="none"
      height={size}
      viewBox="0 0 24 24"
      width={size}
      {...props}
    >
      <g stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.45">
        {paths[name]}
      </g>
    </svg>
  );
}
