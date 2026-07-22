import type { PolicyMode } from "./types";

const STORAGE_KEY = "tokenwise.policy-mode";
const DEFAULT_POLICY_MODE: PolicyMode = "balanced";

export interface PolicyPreference {
  mode: PolicyMode;
  persistenceAvailable: boolean;
}

export function loadPolicyPreference(): PolicyPreference {
  if (typeof window === "undefined") {
    return { mode: DEFAULT_POLICY_MODE, persistenceAvailable: false };
  }

  try {
    const storedMode = window.localStorage.getItem(STORAGE_KEY);
    return {
      mode: isPolicyMode(storedMode) ? storedMode : DEFAULT_POLICY_MODE,
      persistenceAvailable: true,
    };
  } catch (error) {
    console.warn("TokenWise could not read the saved policy preference.", error);
    return { mode: DEFAULT_POLICY_MODE, persistenceAvailable: false };
  }
}

export function savePolicyPreference(mode: PolicyMode): boolean {
  try {
    window.localStorage.setItem(STORAGE_KEY, mode);
    return true;
  } catch (error) {
    console.warn("TokenWise could not save the policy preference.", error);
    return false;
  }
}

function isPolicyMode(value: unknown): value is PolicyMode {
  return (
    value === "conservative" || value === "balanced" || value === "aggressive"
  );
}
