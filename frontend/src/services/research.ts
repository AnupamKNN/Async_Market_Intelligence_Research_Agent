import { API_BASE_URL, apiRequest } from "./api";

export interface ResearchRequest {
  question: string;
  conversation_id?: string;
  requested_sources?: ("internal" | "external")[];
  start_date?: string | null;
  end_date?: string | null;
  fred_series_ids?: string[];
  news_query?: string | null;
  max_articles?: number;
  product_limit?: number;
}

export interface ResearchJobAccepted {
  job_id: string;
  conversation_id: string;
  status: "queued";
  status_url: string;
  events_url: string;
}

export interface ResearchJobResult {
  report?: string;
  analyst_findings?: unknown;
  collector_findings?: unknown;
  evidence_grade?: unknown;
  quantitative_analysis?: unknown;
  errors?: string[];
}

export interface ResearchJobResponse {
  job_id: string;
  question: string;
  status: "queued" | "running" | "completed" | "failed";
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  result: ResearchJobResult | null;
  error: string | null;
}

export interface ResearchConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  job_count: number;
  last_message_at: string | null;
}

export interface ResearchConversationDetail
  extends ResearchConversationSummary {
  jobs: ResearchJobResponse[];
}

export interface ResearchEventPayload {
  message?: string;
  stage?: string;
  status?: string;
}

export const researchApi = {
  submit: (payload: ResearchRequest) =>
    apiRequest<ResearchJobAccepted>("/research/jobs", {
      method: "POST",
      body: payload,
    }),

  getJob: (jobId: string) =>
    apiRequest<ResearchJobResponse>(
      `/research/jobs/${encodeURIComponent(jobId)}`,
    ),

  listConversations: () =>
    apiRequest<ResearchConversationSummary[]>("/conversations"),

  getConversation: (conversationId: string) =>
    apiRequest<ResearchConversationDetail>(
      `/conversations/${encodeURIComponent(conversationId)}`,
    ),

  // The API returns an events URL for newly accepted jobs. Resolve it against
  // the API base while preserving the existing API prefix.
  eventsUrl: (eventsUrl: string) =>
    new URL(eventsUrl, API_BASE_URL).toString(),

  // Conversation history stores the job ID, not its original events URL.
  // Rebuild the same endpoint when reconnecting to an active historical job.
  jobEventsUrl: (jobId: string) =>
    `${API_BASE_URL}/research/jobs/${encodeURIComponent(jobId)}/events`,
};
