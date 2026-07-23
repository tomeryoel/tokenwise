import type { RunResponse } from "./types";

/** In-memory Playground session (not persisted to browser storage). */
export interface PlaygroundSession {
  prompt: string;
  loading: boolean;
  result: RunResponse | null;
  error: string | null;
  attachment: File | null;
  submittedPrompt: string | null;
  submittedAttachmentName: string | null;
}

export const initialPlaygroundSession = (): PlaygroundSession => ({
  prompt: "",
  loading: false,
  result: null,
  error: null,
  attachment: null,
  submittedPrompt: null,
  submittedAttachmentName: null,
});
