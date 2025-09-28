import { useEffect, useState } from "react";
import { apiFetch } from "../api";

export function useAPI(url) {
  const [response, setResponse] = useState();
  useEffect(() => {
    if (!url) return;
    apiFetch(url).then((res) => setResponse(res));
  }, [url]);
  return response;
}

export function useAPISubscription(url, interval = 10000) {
  const [response, setResponse] = useState();
  useEffect(() => {
    if (!url) return;
    const fetchFunc = () => apiFetch(url).then((res) => setResponse(res));
    const intervalID = setInterval(fetchFunc, interval);
    fetchFunc();
    return () => clearInterval(intervalID);
  }, [url, interval]);
  return response;
}
