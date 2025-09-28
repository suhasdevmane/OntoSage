export class DeviceSelectEvent extends CustomEvent {
  static TYPE = "graphicsDeviceSelect";
  constructor(deviceName) {
    super(DeviceSelectEvent.TYPE, { detail: { deviceName } });
  }
}

export class LoadEvent extends CustomEvent {
  static TYPE = "graphicsLoad";
  constructor(success = true) {
    super(LoadEvent.TYPE, { detail: { success } });
  }
}

export class FloorSelectEvent extends CustomEvent {
  static TYPE = "graphicsFloorSelect";
  constructor(floor) {
    super(FloorSelectEvent.TYPE, { detail: { floor } });
  }
}
