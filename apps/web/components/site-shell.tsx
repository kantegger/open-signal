"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { copy } from "../lib/i18n";
import { Icon, type IconName } from "./icons";

const navigation: Array<{
  key: string;
  label: string;
  href: string;
  icon: IconName;
}> = [
  { key: "current", label: copy.en.current, href: "/", icon: "pulse" },
  { key: "explore", label: "Explore", href: "/explore", icon: "search" },
  { key: "archive", label: copy.en.archive, href: "/editions", icon: "archive" },
  { key: "method", label: copy.en.method, href: "/method", icon: "method" },
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

      <header className="site-header">
        <div className="site-header-inner">
          <Brand />
          <nav aria-label="Primary navigation" className="primary-navigation">
            {navigation.map((item) => {
              const itemActive = active === item.key;
              return (
                <Link
                  aria-current={itemActive ? "page" : undefined}
                  className={`primary-link${itemActive ? " is-active" : ""}`}
                  href={item.href}
                  key={item.key}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <div className="header-status" aria-label={`${copy.en.systemStatus}: ${systemState}`}>
            <span className={`status-dot status-${systemState}`} />
            <span>{systemState}</span>
          </div>
          <button
            aria-controls="mobile-navigation"
            aria-expanded={menuOpen}
            aria-label={menuOpen ? "Close navigation" : "Open navigation"}
            className="icon-button mobile-menu-button"
            onClick={() => setMenuOpen((value) => !value)}
            type="button"
          >
            <Icon name={menuOpen ? "close" : "menu"} size={24} />
          </button>
        </div>
        <nav
          aria-label="Mobile navigation"
          className={`mobile-navigation${menuOpen ? " is-open" : ""}`}
          id="mobile-navigation"
        >
          {navigation.map((item) => {
            const itemActive = active === item.key;
            return (
              <Link
                aria-current={itemActive ? "page" : undefined}
                className={itemActive ? "is-active" : undefined}
                href={item.href}
                key={item.key}
                onClick={() => setMenuOpen(false)}
              >
                <Icon name={item.icon} size={19} />
                {item.label}
              </Link>
            );
          })}
          <p><span className={`status-dot status-${systemState}`} /> {systemState}</p>
        </nav>
      </header>

      <main className="publication-canvas" id="main-content">
        {children}
      </main>
    </div>
  );
}

function Brand() {
  return (
    <Link className="brand" href="/" aria-label="Open Signal home">
      <span className="brand-name">Open Signal</span>
      <span className="brand-beta">Public Beta</span>
    </Link>
  );
}
