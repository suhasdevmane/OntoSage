import { Graph } from "./Graph";
import "./GraphContainer.scss";
import { fieldNameFormatter } from "./util";

export function GraphContainer({ options, history }) {
  const deviceName = options?.deviceName;
  const field = options?.field || "";
  if (deviceName) {
    return (
      <article className="graph-container">
        <h2 className="text-capitalize">{`Last 12 hours: '${fieldNameFormatter(field)}'`}</h2>
        <Graph data={history || []} dataKey={field} />
      </article>
    );
  }
  return <></>;
}
