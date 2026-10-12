import { useSession } from "../session";
import { AsyncView, Badge, PageHeader, useAsync } from "../components/ui";

export function ModelsPage() {
  const { api } = useSession();
  const state = useAsync(() => api.models(), [api]);
  return (
    <>
      <PageHeader title="Model catalog" subtitle="Live gateway models and clearly marked preview placeholders." />
      <AsyncView state={state} isEmpty={(d) => d.items.length === 0} emptyTitle="No models are enabled" emptyHint="IDS has not published any enabled models yet. Contact your IDS representative.">
        {(d) => (
          <ul className="cards" aria-label="Model availability">
            {d.items.filter((m) => m.enabled || m.placeholder).map((m) => (
              <li className="card" key={m.id}>
                <h2>{m.id}</h2>
                <p>{m.provider}</p>
                  <span className="badges">
                    {m.placeholder ? <Badge tone="warn">Preview only - not callable</Badge> : m.capabilities.length === 0 ? <span className="muted">None declared</span> : m.capabilities.map((c) => <Badge key={c} tone="info">{c}</Badge>)}
                  </span>
              </li>
            ))}
          </ul>
        )}
      </AsyncView>
    </>
  );
}