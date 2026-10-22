import { useEffect, useState } from "react";

/** Tracks a CSS media query; used to switch sidebar drawer ↔ fixed panel. */
export function useMediaQuery(query) {
  const [matches, setMatches] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia(query).matches : false
  );

  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = (event) => setMatches(event.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}

/** True below the desktop breakpoint where the sidebar becomes a drawer. */
export function useIsMobile(breakpoint = "(max-width: 1023px)") {
  return useMediaQuery(breakpoint);
}
