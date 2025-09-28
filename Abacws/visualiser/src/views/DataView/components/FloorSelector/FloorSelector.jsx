import { useState } from "react";

export function FloorSelector({ onSelect, current: currentProp }) {
  const [current, setCurrent] = useState(currentProp);
  const onSel = (i) => { onSelect(i); setCurrent(i); };
  const buttons = [];
  for (let i = 0; i <= 7; i++) {
    buttons.push(<FloorButton onSelect={onSel} current={current} number={i} key={i} />);
  }
  return <div className="floor-selector">{buttons}</div>;
}

function FloorButton({ onSelect, current, number }) {
  let text = `${number}`;
  if (number === 0) text = "G";
  else if (number === 7) text = "RF";
  return (
    <button className={current === number ? "active" : ""} onClick={() => { onSelect(number); }}>
      {text}
    </button>
  );
}
