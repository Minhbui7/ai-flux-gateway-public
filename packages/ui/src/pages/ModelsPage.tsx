import { useSession } from "../session";
import { AsyncView, Badge, PageHeader, Table, useAsync } from "../components/ui";

export function ModelsPage() {
  const { api } = useSession();
  const state = useAsync(() => api.models(), [api]);
  return (
    <>
      <PageHeader title="Model catalog" subtitle="Enabled models available to every active subscription through the gateway." />
      <AsyncView state={state} isEmpty={(d) => d.items.length === 0} emptyTitle="No models are enabled" emptyHint="IDS has not published any enabled models yet. Contact your IDS representative.">
        {(d) => (
          <Table caption="Enabled models" head={["Model", "Provider", "Capabilities"]}>
            {d.items.filter((m) => m.enabled).map((m) => (
              <tr key={m.id}>
                <th scope="row">{m.id}</th>
                <td>{m.provider}</td>
                <td>
                  <span className="badges">
                    {m.capabilities.length === 0 ? <span className="muted">None declared</span> : m.capabilities.map((c) => <Badge key={c} tone="info">{c}</Badge>)}
                  </span>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </AsyncView>
    </>
  );
}