import { useEffect, useState } from "react";

/** Current time, re-rendered every `intervalMs` while `active` (countdowns). */
export function useNow(active: boolean, intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [active, intervalMs]);

  return now;
}

/** Seconds left until `deadline` (epoch ms), ticking once per second. */
export function useSecondsLeft(deadline: number | null): number {
  const now = useNow(deadline !== null && deadline > Date.now());
  if (deadline === null) return 0;
  return Math.max(0, Math.ceil((deadline - now) / 1000));
}
