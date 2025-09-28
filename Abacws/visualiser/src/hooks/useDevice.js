import { useAPI, useAPISubscription } from "./useAPI";
import { useTimeContext } from './useTimeContext';

export function useDevices() {
  return useAPI("/api/devices")?.body;
}

export function useDeviceInfo(deviceName) {
  const url = deviceName ? `/api/devices/${deviceName}` : undefined;
  return useAPI(url)?.body;
}

export function useDeviceData(deviceName) {
  const url = deviceName ? `/api/devices/${deviceName}/data` : undefined;
  return useAPISubscription(url)?.body;
}

export function useDeviceHistory(deviceName) {
  const time = useTimeContext();
  const to = time?.to || Date.now();
  const from = time?.from || (to - 12*60*60*1000);
  const url = deviceName ? `/api/devices/${deviceName}/history?to=${to}&from=${from}` : undefined;
  // Poll faster in live mode by temporarily reducing subscription interval logic (reuse existing hook semantics if it honors URL changes)
  return useAPISubscription(url)?.body;
}
