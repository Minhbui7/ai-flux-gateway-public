import { useState } from "react";
import { AsyncView, Pager, fmtDate, useAsync } from "../components/ui";
import type { GatewayConfigurationUnion, GatewayRevision, Paged } from "../types";

export function RevisionHistory({ load, deps, disabled, onUse }: {
  load: (offset: number) => Promise<Paged<GatewayRevision>>;
  deps: unknown[];
  disabled: boolean;
  onUse: (configuration: GatewayConfigurationUnion) => void;
}) {
  const [offset, setOffset] = useState(0);
  const history = useAsync(() => load(offset), [...deps, offset]);
  return <>
    <h3>Revision history</h3>
    <AsyncView state={history} isEmpty={(d) => d.items.length === 0} emptyTitle="No settings revisions" emptyHint="An IDS administrator must explicitly configure the settings.">
      {(data) => <>
        <ul>{data.items.map((revision) => <li key={revision.version}>
          Revision {revision.version}: {revision.state}, {fmtDate(revision.occurred_at)}. Actor: <code>{revision.object_id}</code>. Reason: {revision.reason}.
          <button className="btn" disabled={disabled} onClick={() => onUse(revision.configuration)}>Use revision {revision.version} values</button>
        </li>)}</ul>
        <Pager offset={offset} limit={10} total={data.total} onChange={setOffset} />
      </>}
    </AsyncView>
  </>;
}
