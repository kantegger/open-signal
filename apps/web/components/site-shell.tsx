"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { localePath, SUPPORTED_LOCALES } from "../lib/i18n";
import { Icon, type IconName } from "./icons";
import { useLocale } from "./locale-provider";

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
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { locale, text } = useLocale();
  const navigation: Array<{
    key: string;
    label: string;
    href: string;
    icon: IconName;
  }> = [
    { key: "current", label: text.current, href: localePath("/", locale), icon: "pulse" },
    { key: "explore", label: text.explore, href: localePath("/explore", locale), icon: "search" },
    { key: "archive", label: text.archive, href: localePath("/editions", locale), icon: "archive" },
    { key: "method", label: text.method, href: localePath("/method", locale), icon: "method" },
  ];
  const query = searchParams.toString();
  const currentLocation = `${pathname}${query ? `?${query}` : ""}`;
  const stateLabel =
    systemState === "operational"
      ? text.operational
      : systemState === "unavailable"
        ? text.unavailable
        : systemState === "checking"
          ? text.checking
          : systemState;

  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [menuOpen]);

  return (
    <div className="site-frame" data-active-route={active}>
      <a className="skip-link" href="#main-content">{text.skipToPublication}</a>

      <header className="site-header">
        <div className="site-header-inner">
          <Brand />
          <nav aria-label={text.primaryNavigation} className="primary-navigation">
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
          <div className="header-status" aria-label={`${text.systemStatus}: ${stateLabel}`}>
            <span className={`status-dot status-${systemState}`} />
            <span>{stateLabel}</span>
          </div>
          <nav className="language-switcher" aria-label={text.language}>
            {SUPPORTED_LOCALES.map((candidate) => (
              <a
                aria-current={candidate === locale ? "page" : undefined}
                className={candidate === locale ? "is-active" : undefined}
                href={localePath(currentLocation, candidate)}
                hrefLang={candidate}
                key={candidate}
                lang={candidate}
              >
                {candidate === "en" ? "EN" : "繁中"}
              </a>
            ))}
          </nav>
          <button
            aria-controls="mobile-navigation"
            aria-expanded={menuOpen}
            aria-label={menuOpen ? text.closeNavigation : text.openNavigation}
            className="icon-button mobile-menu-button"
            onClick={() => setMenuOpen((value) => !value)}
            type="button"
          >
            <Icon name={menuOpen ? "close" : "menu"} size={24} />
          </button>
        </div>
        <nav
          aria-label={text.mobileNavigation}
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
          <div className="mobile-language-switcher" aria-label={text.language}>
            {SUPPORTED_LOCALES.map((candidate) => (
              <a
                className={candidate === locale ? "is-active" : undefined}
                href={localePath(currentLocation, candidate)}
                hrefLang={candidate}
                key={candidate}
                lang={candidate}
                onClick={() => setMenuOpen(false)}
              >
                {candidate === "en" ? text.english : text.traditionalChinese}
              </a>
            ))}
          </div>
          <p><span className={`status-dot status-${systemState}`} /> {stateLabel}</p>
        </nav>
      </header>

      <main className="publication-canvas" id="main-content">
        {children}
      </main>
    </div>
  );
}

function Brand() {
  const { locale, text } = useLocale();
  return (
    <Link className="brand" href={localePath("/", locale)} aria-label={text.homeLabel}>
      <span className="brand-name">{text.brand}</span>
      <span className="brand-beta">{text.beta}</span>
    </Link>
  );
}
