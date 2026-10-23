// Camera interpolation shares the map's render loop; it owns no timers.
export function createCameraMotion({
  read,
  write,
  requestFrame,
  reduced,
  light = () => false,
  now = () => performance.now(),
}) {
  let flight = null;
  const blend = (a, b, t) => a + (b - a) * t;
  function finish() {
    if (!flight) return;
    const target = flight.target;
    flight = null;
    write({ ...target });
    requestFrame();
  }
  return {
    get active() {
      return !!flight;
    },
    destination(kind) {
      return { ...(flight?.kind === kind ? flight.target : read()) };
    },
    cancel() {
      flight = null;
    },
    finish,
    to(target, { duration = 600, kind = "focus", panoramic = false } = {}) {
      if (light()) {
        duration = Math.min(duration, 280);
        panoramic = false;
      }
      const from = { ...read() };
      const goal = { ...from, ...target };
      // Take the shorter orbit, including after repeated rotate-button presses.
      goal.yaw =
        from.yaw +
        Math.atan2(
          Math.sin(goal.yaw - from.yaw),
          Math.cos(goal.yaw - from.yaw),
        );
      const distance = Math.hypot(goal.cx - from.cx, goal.cz - from.cz);
      const cruise = Math.max(
        0.5,
        Math.min(from.scale, goal.scale, 70 / (distance + 35)),
      );
      flight = {
        from,
        target: goal,
        started: now(),
        duration,
        kind,
        dip:
          panoramic && distance > 18
            ? Math.max(0, Math.log(Math.sqrt(from.scale * goal.scale) / cruise))
            : 0,
      };
      if (reduced() || duration <= 0) finish();
      else requestFrame();
    },
    step(time) {
      if (!flight) return false;
      if (reduced()) {
        finish();
        return false;
      }
      const { from, target, started, duration, kind, dip } = flight;
      const progress = Math.max(0, Math.min(1, (time - started) / duration));
      const t =
        kind === "zoom"
          ? 1 - (1 - progress) ** 3
          : progress * progress * (3 - 2 * progress);
      const value = {};
      for (const key of ["cx", "cz", "yaw", "tilt"])
        value[key] = blend(from[key], target[key], t);
      value.scale = Math.max(
        Math.min(0.5, from.scale, target.scale),
        Math.min(
          16,
          Math.exp(
            blend(Math.log(from.scale), Math.log(target.scale), t) -
              dip * Math.sin(Math.PI * t) ** 2,
          ),
        ),
      );
      write(progress === 1 ? { ...target } : value);
      if (progress === 1) flight = null;
      return !!flight;
    },
  };
}
