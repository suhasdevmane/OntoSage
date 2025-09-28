import { Icons } from "../../../../components";
import "./DeviceDetails.scss";

function DataRow({ field, value, units, onViewHistory }) {
  const options = onViewHistory ? (
    <button onClick={() => { onViewHistory(); }} className="primary">History</button>
  ) : (
    "N/A"
  );
  return (
    <tr>
      <th headers="field" scope="row">{field}</th>
      <td headers={`value ${field}`}>{value}</td>
      <td headers={`units ${field}`}>{units ? units : "N/A"}</td>
      <td headers={`options ${field}`}>{options}</td>
    </tr>
  );
}

export function DeviceDetails({ device, data, onViewHistory }) {
  // Suppress UI entirely until a device is selected
  if (!device?.name) return null;
  const rows = [];
  const timestamp = new Date(Number(data?.timestamp)).toLocaleString();
  rows.push(<DataRow field="timestamp" key="timestamp" value={timestamp} />);
  if (data) {
    rows.push(Object.entries(data).map(([key, value]) => {
      if (key === "timestamp") return null;
      if (value?.value !== undefined) {
        return (
          <DataRow
            key={key}
            field={key}
            onViewHistory={() => { onViewHistory(device?.name, `${key}.value`); }}
            value={value.value}
            units={value?.units}
          />
        );
      }
      return (
        <DataRow
          key={key}
          field={key}
          onViewHistory={() => { onViewHistory(device?.name, key); }}
          value={String(value)}
        />
      );
    }));
  }
  const exportIcon = device?.name ? (
    <a href={`/api/devices/${device?.name}/history`} className="export-link" download={`${device?.name}.json`}>
      <Icons.Export />
    </a>
  ) : undefined;
  return (
    <article className="device-container">
      <h2>Device: '<span className="text-capitalize">{device.name}</span>'</h2>
      <p>Type:&nbsp;<span className="text-capitalize">{device?.type ? device?.type : "N/A"}</span></p>
      <p>Floor:&nbsp;<span className="text-capitalize">{device?.floor !== undefined ? device?.floor : "N/A"}</span></p>
      {exportIcon}
      <table className="data">
        <thead>
          <tr>
            <th scope="column">field</th>
            <th scope="column">value</th>
            <th scope="column">units</th>
            <th scope="column">options</th>
          </tr>
        </thead>
        <tbody>
          {data ? rows : <tr><td colSpan={4}>No data</td></tr>}
        </tbody>
      </table>
    </article>
  );
}
