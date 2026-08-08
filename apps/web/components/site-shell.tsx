"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { copy } from "../lib/i18n";
import { Icon, type IconName } from "./icons";

const navigation: Array<{
  label: string;
  href: string;
  icon: IconName;
  section?: string;
}> = [
  { label: copy.en.current, href: "/", icon: "pulse" },
  { label: copy.en.expectations, href: "/#expectations", icon: "trend", section: "expectations" },
  { label: copy.en.rules, href: "/#rules", icon: "document", section: "rules" },
  { label: copy.en.research, href: "/#research", icon: "search", section: "research" },
  { label: copy.en.method, href: "/#method", icon: "method" },
  { label: copy.en.archive, href: "/#archive", icon: "archive" },
];

export function SiteShell({
  children,
  active = "current",
  systemState = "operational",
}: {
  children: React.ReactNode;
  active?: string;
  systemState?: string;
}) {
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [menuOpen]);

  return (
    <div className="site-frame">
      <a className="skip-link" href="#main-content">Skip to publication</a>

      <aside className="site-rail" aria-label="Primary navigation">
        <Brand />
        <nav className="rail-navigation">
          {navigation.map((item) => {
            const itemActive = active === (item.section ?? item.label.toLowerCase());
            return (
              <Link
                aria-current={itemActive ? "page" : undefined}
                className={`rail-link${itemActive ? " is-active" : ""}`}
                href={item.href}
                key={item.label}
              >
                <Icon name={item.icon} size={23} />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="rail-status">
          <span className={`status-dot status-${systemState}`} />
          <span>{copy.en.systemStatus}</span>
          <small>{systemState}</small>
        </div>
      </aside>

      <header className="mobile-header">
        <Brand compact />
        <button
          aria-controls="mobile-navigation"
          aria-expanded={menuOpen}
          aria-label={menuOpen ? "Close navigation" : "Open navigation"}
          className="icon-button mobile-menu-button"
          onClick={() => setMenuOpen((value) => !value)}
          type="button"
        >
          <Icon name={menuOpen ? "close" : "menu"} size={28} />
        </button>
        <nav
          className={`mobile-navigation${menuOpen ? " is-open" : ""}`}
          id="mobile-navigation"
        >
          {navigation.map((item) => (
            <Link href={item.href} key={item.label} onClick={() => setMenuOpen(false)}>
              <Icon name={item.icon} size={20} />
              {item.label}
            </Link>
          ))}
          <p><span className={`status-dot status-${systemState}`} /> {systemState}</p>
        </nav>
      </header>

      <main className="publication-canvas" id="main-content">
        {children}
      </main>
    </div>
  );
}

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link className={`brand${compact ? " brand-compact" : ""}`} href="/" aria-label="Open Signal home">
      <span className="brand-name">Open Signal</span>
      <span className="brand-beta">Public Beta</span>
    </Link>
  );
}
