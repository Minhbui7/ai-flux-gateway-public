import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthGate, GatewaySettingsPage, MembersPage, OrganizationsPage, PricesPage, SafetyPage, Shell, UsagePage, type NavItem } from "@aiflux/ui";

const nav: NavItem[] = [
  { to: "/usage", label: "Showback" },
  { to: "/safety", label: "Safety events" },
  { to: "/settings", label: "Gateway settings" },
  { to: "/organizations", label: "Organizations" },
  { to: "/members", label: "Members" },
  { to: "/prices", label: "Prices" },
];

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthGate portalName="IDS admin portal" allowedRoles={["ids_admin"]} env={import.meta.env}>
      <BrowserRouter basename="/admin">
        <Routes>
          <Route element={<Shell portalName="IDS admin portal" nav={nav} />}>
            <Route index element={<Navigate to="/usage" replace />} />
            <Route path="/usage" element={<UsagePage admin />} />
            <Route path="/safety" element={<SafetyPage />} />
            <Route path="/settings" element={<GatewaySettingsPage />} />
            <Route path="/organizations" element={<OrganizationsPage />} />
            <Route path="/members" element={<MembersPage />} />
            <Route path="/prices" element={<PricesPage />} />
            <Route path="*" element={<Navigate to="/usage" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthGate>
  </StrictMode>,
);