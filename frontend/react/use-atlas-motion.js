import { useState, useEffect } from "react";
export function useAtlasMotion() {
  const read = () =>
    window.AtlasUI.motion.isReduced() || window.AtlasUI.performance.isCitrix();
  const [reduced, setReduced] = useState(read);
  useEffect(() => {
    const update = () => setReduced(read());
    window.addEventListener("atlas-motion-change", update);
    return () => window.removeEventListener("atlas-motion-change", update);
  }, []);
  return reduced;
}
