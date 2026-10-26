import { Stats } from './api.models';

export const NO_LLM_TOKEN = 'No LLM token provided — the app cannot process invoices without it';

/** The environment variable to set when stats report no LLM key; null while configured or before stats load. */
export function missingLlmKey(stats: Stats | undefined): string | null {
  const llm = stats?.llm;
  return llm && !llm.configured ? (llm.missing_key ?? 'XAI_API_KEY or ANTHROPIC_API_KEY') : null;
}

export function setKeyHint(key: string): string {
  return `Set ${key} in .env and restart the backend.`;
}
