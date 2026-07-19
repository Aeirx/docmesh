import { useEffect, useState } from "react";

/** Returns `value` after it has been stable for `delayMs`. Standard trailing
 *  debounce — the graph filter uses it so each keystroke doesn't fire a fetch. */
export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
