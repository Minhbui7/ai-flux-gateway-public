import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useSession } from "../session";
import { BrandMark } from "./ui";

export interface NavItem {
  to: string;
  label: string;
}

export function Shell({ portalName, nav }: { portalName: string; nav: NavItem[] }) {
  const { me, signOut } = useSession();
  const [open, setOpen] = useState(false);
  return (
    <div className="shell">
      <a className="skip" href="#main">Skip to content</a>
      <header className="topbar">
        <BrandMark />
        <span className="portal-name">{portalName}</span>
        <button className="btn menu-btn" aria-expanded={open} aria-controls="sidenav" onClick={() => setOpen(!open)}>Menu</button>
        <div className="who">
          <span><strong>{me.organization_name}</strong><small>{me.role === "ids_admin" ? "IDS administrator" : "Customer"}</small></span>
          <button className="btn" onClick={signOut}>Sign out</button>
        </div>
      </header>
      <div className="body">
        <nav id="sidenav" className={open ? "side open" : "side"} aria-label="Primary">
          {nav.map((n) => (
            <NavLink key={n.to} to={n.to} onClick={() => setOpen(false)}>{n.label}</NavLink>
          ))}
        </nav>
        <main id="main" className="content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}