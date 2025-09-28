import { useState } from "react";
import { apiFetch } from "../../../../api";
import "./QueryPanel.scss";

export function QueryPanel() {
  const [hideHas, setHideHas] = useState(true);
  const [hideDateRange, setHideDateRange] = useState(true);
  return (
    <article>
      <form
        className="query-form"
        id="query-form"
        autoComplete="off"
        onReset={() => { setHideHas(true); setHideDateRange(true); }}
        onSubmit={async (e) => {
          e.preventDefault();
          const form = e.target;
          const fromTime = String(new Date(form.from.value).getTime());
          const toTime = String(new Date(form.to.value).getTime());
          const queryType = form.queryType.value;
          let baseUrl = `${window.location.protocol}${window.location.host}/api/query`;
          if (queryType !== "info") baseUrl = `${baseUrl}/${queryType}`;
          const url = new URL(baseUrl);
          if (form.name.value) url.searchParams.set("name", form.name.value);
          if (form.type.value) url.searchParams.set("type", form.type.value);
          if (form.floor.value) url.searchParams.set("floor", form.floor.value);
          if (form.has.value) url.searchParams.set("has", form.has.value);
          if (form.from.value) url.searchParams.set("from", fromTime);
          if (form.to.value) url.searchParams.set("to", toTime);
          const result = await (await apiFetch(url.toString())).body;
          const blob = new Blob([JSON.stringify(result)], { type: "text/json" });
          const blobUrl = window.URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.download = "query.json";
          a.href = blobUrl;
          a.dispatchEvent(new MouseEvent('click', { view: window, bubbles: true, cancelable: true }));
          a.remove();
        }}
      >
        <h2 className="title">Advanced Query</h2>
        <div className="input-group">
          <span className="label-container"><label htmlFor="queryType">Query Type:</label></span>
          <select id="queryType" name="queryType" defaultValue="info" onChange={(e) => {
            const value = e.target.value; setHideHas(value === "info"); setHideDateRange(value !== "history");
          }}>
            <option>info</option>
            <option>data</option>
            <option>history</option>
          </select>
        </div>
        <div className="input-group">
          <span className="label-container"><label htmlFor="name">Name:</label></span>
          <input id="name" name="name" type="text" placeholder="sensor1,sensor2" />
        </div>
        <div className="input-group">
          <span className="label-container"><label htmlFor="type">Type:</label></span>
          <input id="type" name="type" type="text" placeholder="lecture,office" />
        </div>
        <div className="input-group">
          <span className="label-container"><label htmlFor="floor">Floor:</label></span>
          <input id="floor" name="floor" type="text" placeholder="1,2" />
        </div>
        <div className={hideHas ? "input-group hidden" : "input-group"}>
          <span className="label-container"><label htmlFor="has">Has:</label></span>
          <input id="has" name="has" type="text" placeholder="temperature,humidity" />
        </div>
        <div className={hideDateRange ? "input-group hidden" : "input-group"}>
          <span className="label-container"><label htmlFor="from">From:</label></span>
          <input id="from" name="from" type="datetime-local" />
        </div>
        <div className={hideDateRange ? "input-group hidden" : "input-group"}>
          <span className="label-container"><label htmlFor="to">To:</label></span>
          <input id="to" name="to" type="datetime-local" />
        </div>
        <footer className="footer">
          <input className="button primary" type="submit" />
          <input className="button danger" type="reset" />
        </footer>
      </form>
    </article>
  );
}
