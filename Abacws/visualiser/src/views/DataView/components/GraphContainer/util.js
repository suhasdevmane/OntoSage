export function unixTimeFormatter(value) {
  return new Date(Number(value)).toLocaleTimeString();
}

export function fieldNameFormatter(value) {
  return value.split(".")[0];
}
