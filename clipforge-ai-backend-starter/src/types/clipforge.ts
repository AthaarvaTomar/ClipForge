export type ProjectStatus =
  | "draft"
  | "uploading"
  | "uploaded"
  | "analyzing"
  | "ready"
  | "failed";

export type JobStatus = "queued" | "processing" | "completed" | "failed";

export type ClipSuggestion = {
  id: string;
  projectId: string;
  title: string;
  rationale: string | null;
  startSeconds: number;
  endSeconds: number;
  score: number | null;
  transcriptExcerpt: string | null;
};
