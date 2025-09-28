export function Icon(props) {
  return (
    <div role="img" aria-label="icon" {...props} className={`icon ${props.className || ""}`} />
  );
}
