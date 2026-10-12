import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthGate, ModelsPage, PlaygroundPage, Shell, SubscriptionsPage, UsagePage, type NavItem } from "@aiflux/ui";

const nav: NavItem[] = [
  { to: "/models", label: "Models" },
  { to: "/subscriptions", label: "Subscriptions" },
  { to: "/playground", label: "Playground" },
  { to: "/usage", label: "Usage & cost" },
];

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthGate portalName="Customer portal" allowedRoles={["customer", "ids_admin"]} env={import.meta.env}>
      <BrowserRouter>
        <Routes>
          <Route element={<Shell portalName="Customer portal" nav={nav} />}>
            <Route index element={<Navigate to="/models" replace />} />
            <Route path="/models" element={<ModelsPage />} />
            <Route path="/subscriptions" element={<SubscriptionsPage />} />
            <Route path="/playground" element={<PlaygroundPage />} />
            <Route path="/usage" element={<UsagePage />} />
            <Route path="*" element={<Navigate to="/models" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthGate>
  </StrictMode>,
);