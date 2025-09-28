import { Icon } from "./Icon";
import "./Icons.scss";

export function Export(props) {
  const className = `export ${props.className || ""}`;
  return (<Icon {...props} className={className} />);
}
