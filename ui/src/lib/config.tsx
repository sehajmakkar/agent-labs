import { createContext, useContext, useState, type ReactNode } from "react";

import { api, DEMO_KEY_STORAGE, type LabConfig } from "../api";
import { useLoad } from "./hooks";

const LOCAL: LabConfig = {
  public: false,
  actions: { replay: true, fork: true, blame: true, lock_in: true },
  max_n: 20,
  repo: "https://github.com/sehajmakkar/agent-labs",
};

const ConfigContext = createContext<LabConfig>(LOCAL);

export function ConfigProvider({ children }: { children: ReactNode }) {
  const config = useLoad(api.config, "config");
  return <ConfigContext.Provider value={config.data ?? LOCAL}>{children}</ConfigContext.Provider>;
}

export function useConfig(): LabConfig {
  return useContext(ConfigContext);
}

/** Whether an action can run here, and if not, why (shown as the button's tooltip). */
export function useAction(action: "fork" | "blame" | "lock_in"): { allowed: boolean; why?: string } {
  const config = useConfig();
  const setting = config.actions[action];
  if (setting === true) return { allowed: true };
  if (setting === "key") {
    return hasDemoKey()
      ? { allowed: true }
      : { allowed: false, why: "Uses real model calls: enter a demo key (top right) to try it" };
  }
  return { allowed: false, why: "Switched off on the hosted demo: run the lab locally" };
}

export function hasDemoKey(): boolean {
  try {
    return !!window.localStorage.getItem(DEMO_KEY_STORAGE);
  } catch {
    return false;
  }
}

/** The small "demo key" control in the nav, only on the hosted demo. */
export function DemoKey() {
  const config = useConfig();
  const [, setTick] = useState(0);
  if (!config.public) return null;
  const set = hasDemoKey();
  function change() {
    const value = window.prompt(set ? "Demo key (empty to remove)" : "Demo key, to try forks and blames");
    if (value === null) return;
    try {
      if (value) window.localStorage.setItem(DEMO_KEY_STORAGE, value.trim());
      else window.localStorage.removeItem(DEMO_KEY_STORAGE);
    } catch {
      /* storage blocked: the key just won't be remembered */
    }
    setTick((t) => t + 1);
  }
  return (
    <button className="demo-key" onClick={change} title="Forks and blames spend real model calls">
      {set ? "🔑 Demo key set" : "🔑 Demo key"}
    </button>
  );
}
