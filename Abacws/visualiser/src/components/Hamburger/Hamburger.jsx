import "./Hamburger.scss";

export function HamburgerToggle({ onClick, close }) {
  const className = close ? "hamburger-toggle close" : "hamburger-toggle";
  return (
    <div onClick={onClick} className={className}>
      <div className="slice"></div>
      <div className="slice"></div>
      <div className="slice"></div>
    </div>
  );
}
