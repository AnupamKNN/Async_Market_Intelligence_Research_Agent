import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import {
  Activity,
  ArrowUp,
  CheckCircle2,
  CircleAlert,
  Database,
  LoaderCircle,
  LogOut,
  Menu,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  Workflow,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../context/useAuth";
import {
  researchApi,
  type ResearchConversationSummary,
  type ResearchEventPayload,
  type ResearchJobResponse,
} from "../services/research";
import "./WorkspacePage.css";

interface ProgressItem {
  stage: string;
  message: string;
}

interface UserMessage {
  id: string;
  role: "user";
  content: string;
}

type ResearchStatus =
  | "submitting"
  | "queued"
  | "running"
  | "completed"
  | "failed";

interface AssistantMessage {
  id: string;
  role: "assistant";
  status: ResearchStatus;
  jobId?: string;
  progress: ProgressItem[];
  statusMessage?: string;
  report?: string;
  error?: string;
  reportError?: string;
  connection: "connecting" | "connected" | "reconnecting" | "closed";
}

type ChatMessage = UserMessage | AssistantMessage;

const suggestions = [
  {
    icon: Database,
    category: "DATA ANALYTICS",
    title: "Explore sales performance",
    description: "Discover revenue trends and top-performing products.",
    prompt:
      "Analyze sales performance, identify the top revenue-driving products, and explain the monthly revenue trends.",
  },
  {
    icon: Search,
    category: "MARKET RESEARCH",
    title: "Understand customer markets",
    description: "Compare purchasing patterns across countries.",
    prompt:
      "Compare customer purchasing patterns across countries and identify the most valuable markets.",
  },
  {
    icon: Workflow,
    category: "BUSINESS INTELLIGENCE",
    title: "Investigate business trends",
    description: "Find patterns, anomalies and potential risks.",
    prompt:
      "Analyze the available retail data for important business trends, anomalies, and potential risks.",
  },
];

function createId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function parseEventPayload(data: string): ResearchEventPayload {
  try {
    const parsed: unknown = JSON.parse(data);

    if (parsed && typeof parsed === "object") {
      return parsed as ResearchEventPayload;
    }
  } catch {
    // Ignore malformed event payloads and use an empty payload.
  }

  return {};
}

function formatStage(stage: string): string {
  return stage
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function toChatMessages(jobs: ResearchJobResponse[]): ChatMessage[] {
  return jobs.flatMap((job): ChatMessage[] => {
    const report =
      typeof job.result?.report === "string" && job.result.report.trim()
        ? job.result.report
        : undefined;

    const isActive = job.status === "queued" || job.status === "running";

    const userMessage: UserMessage = {
      id: `${job.job_id}-user`,
      role: "user",
      content: job.question,
    };

    const assistantMessage: AssistantMessage = {
      id: job.job_id,
      role: "assistant",
      status: job.status,
      jobId: job.job_id,
      progress: [],
      statusMessage: isActive
        ? "Reconnecting to live research updates."
        : undefined,
      report,
      reportError:
        job.status === "completed" && !report
          ? "The job completed, but no report was returned."
          : undefined,
      error: job.error || undefined,
      connection: isActive ? "connecting" : "closed",
    };

    return [userMessage, assistantMessage];
  });
}

export default function WorkspacePage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  const [conversationId, setConversationId] = useState<string | null>(null);

  const [conversations, setConversations] = useState<
    ResearchConversationSummary[]
  >([]);

  const [historyQuery, setHistoryQuery] = useState("");
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState("");

  const [loadingConversationId, setLoadingConversationId] = useState<
    string | null
  >(null);

  const [sending, setSending] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState("");
  const [composerError, setComposerError] = useState("");

  const promptRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const eventSourcesRef = useRef<Map<string, EventSource>>(new Map());

  const messagesRef = useRef<Map<string, AssistantMessage>>(new Map());

  const conversationLoadSequenceRef = useRef(0);

  const displayName = user?.display_name || "Researcher";
  const email = user?.email || "";

  const initials = displayName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();

  const filteredConversations = useMemo(() => {
    const query = historyQuery.trim().toLowerCase();

    if (!query) {
      return conversations;
    }

    return conversations.filter((conversation) =>
      conversation.title.toLowerCase().includes(query),
    );
  }, [conversations, historyQuery]);

  // Refresh the conversation list after new jobs are submitted or completed.
  const refreshConversationList = useCallback(async () => {
    try {
      const data = await researchApi.listConversations();

      setConversations(data);
      setHistoryError("");
    } catch (error) {
      setHistoryError(
        error instanceof Error
          ? error.message
          : "Unable to load conversation history.",
      );
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  // Load conversation history when the workspace mounts.
  // State updates occur after the asynchronous request settles.
  useEffect(() => {
    let isActive = true;

    void researchApi
      .listConversations()
      .then((data) => {
        if (!isActive) {
          return;
        }

        setConversations(data);
        setHistoryError("");
      })
      .catch((error: unknown) => {
        if (!isActive) {
          return;
        }

        setHistoryError(
          error instanceof Error
            ? error.message
            : "Unable to load conversation history.",
        );
      })
      .finally(() => {
        if (isActive) {
          setHistoryLoading(false);
        }
      });

    return () => {
      isActive = false;
    };
  }, []);

  // Scroll to the latest message whenever the thread changes.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "end",
    });
  }, [messages]);

  // Keep the latest assistant messages available to SSE callbacks.
  useEffect(() => {
    const latest = new Map<string, AssistantMessage>();

    messages.forEach((message) => {
      if (message.role === "assistant") {
        latest.set(message.id, message);
      }
    });

    messagesRef.current = latest;
  }, [messages]);

  // Close all event streams when the workspace unmounts.
  useEffect(() => {
    const eventSources = eventSourcesRef.current;

    return () => {
      eventSources.forEach((source) => source.close());
      eventSources.clear();
    };
  }, []);

  function updateAssistant(
    id: string,
    update: Partial<AssistantMessage>,
  ) {
    // Keep the event-handler ref synchronized immediately.
    // Multiple progress events can arrive before React commits a render.
    const currentAssistant = messagesRef.current.get(id);

    if (currentAssistant) {
      messagesRef.current.set(id, {
        ...currentAssistant,
        ...update,
      });
    }

    setMessages((current) =>
      current.map((message) => {
        if (message.id !== id || message.role !== "assistant") {
          return message;
        }

        return {
          ...message,
          ...update,
        };
      }),
    );
  }

  function closeResearchStreams() {
    eventSourcesRef.current.forEach((source) => source.close());
    eventSourcesRef.current.clear();
  }

  function startNewChat() {
    // Do not detach the UI while a submission is waiting for its
    // conversation ID.
    if (sending) {
      return;
    }

    conversationLoadSequenceRef.current += 1;

    closeResearchStreams();

    setConversationId(null);
    setLoadingConversationId(null);

    messagesRef.current.clear();

    setMessages([]);
    setPrompt("");
    setComposerError("");
    setHistoryError("");
    setMobileSidebarOpen(false);

    promptRef.current?.focus();
  }

  function selectSuggestion(value: string) {
    setPrompt(value);
    setComposerError("");
    promptRef.current?.focus();
  }

  async function retrieveCompletedReport(
    assistantId: string,
    jobId: string,
  ) {
    try {
      const job = await researchApi.getJob(jobId);

      if (job.status === "failed") {
        updateAssistant(assistantId, {
          status: "failed",
          error: job.error || "Research execution failed.",
          connection: "closed",
        });

        return;
      }

      const report = job.result?.report;

      updateAssistant(assistantId, {
        status: "completed",

        report:
          typeof report === "string" && report.trim()
            ? report
            : undefined,

        reportError:
          typeof report === "string" && report.trim()
            ? undefined
            : "The job completed, but no report was returned.",

        connection: "closed",
      });
    } catch (error) {
      updateAssistant(assistantId, {
        status: "completed",

        reportError:
          error instanceof Error
            ? `Unable to retrieve the completed report: ${error.message}`
            : "Unable to retrieve the completed report.",

        connection: "closed",
      });
    }
  }

  async function retrieveFailedJob(
    assistantId: string,
    jobId: string,
    fallbackMessage: string,
  ) {
    try {
      const job = await researchApi.getJob(jobId);

      updateAssistant(assistantId, {
        status: "failed",
        error: job.error || fallbackMessage,
        connection: "closed",
      });
    } catch {
      updateAssistant(assistantId, {
        status: "failed",
        error: fallbackMessage,
        connection: "closed",
      });
    }
  }

  function connectToResearchEvents(
    assistantId: string,
    jobId: string,
    eventsUrl: string,
  ) {
    // Avoid creating duplicate EventSource connections.
    eventSourcesRef.current.get(assistantId)?.close();

    const source = new EventSource(
      researchApi.eventsUrl(eventsUrl),
      {
        withCredentials: true,
      },
    );

    eventSourcesRef.current.set(assistantId, source);

    // The backend replays events from the beginning on reconnect.
    // De-duplicate using Redis Stream event IDs.
    const seenEventIds = new Set<string>();

    source.onopen = () => {
      updateAssistant(assistantId, {
        connection: "connected",
      });
    };

    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) {
        eventSourcesRef.current.delete(assistantId);

        updateAssistant(assistantId, {
          connection: "closed",
        });
      } else {
        updateAssistant(assistantId, {
          connection: "reconnecting",
        });
      }
    };

    function registerEvent(
      eventName: string,
      callback: (payload: ResearchEventPayload) => void,
    ) {
      const handler: EventListener = (event) => {
        const messageEvent = event as MessageEvent<string>;

        if (
          messageEvent.lastEventId &&
          seenEventIds.has(messageEvent.lastEventId)
        ) {
          return;
        }

        if (messageEvent.lastEventId) {
          seenEventIds.add(messageEvent.lastEventId);
        }

        callback(parseEventPayload(messageEvent.data));
      };

      source.addEventListener(eventName, handler);
    }

    registerEvent("queued", (payload) => {
      updateAssistant(assistantId, {
        status: "queued",
        statusMessage:
          payload.message || "Research job accepted and queued.",
      });
    });

    registerEvent("started", (payload) => {
      updateAssistant(assistantId, {
        status: "running",
        statusMessage:
          payload.message || "Research execution started.",
      });
    });

    registerEvent("progress", (payload) => {
      const previousProgress =
        messagesRef.current.get(assistantId)?.progress ?? [];

      updateAssistant(assistantId, {
        status: "running",

        progress: [
          ...previousProgress,
          {
            stage: payload.stage || "research",
            message: payload.message || "Research stage updated.",
          },
        ],
      });
    });

    registerEvent("completed", () => {
      source.close();
      eventSourcesRef.current.delete(assistantId);

      updateAssistant(assistantId, {
        status: "completed",
        statusMessage: "Research execution completed.",
        connection: "closed",
      });

      void retrieveCompletedReport(assistantId, jobId);
      void refreshConversationList();
    });

    registerEvent("failed", (payload) => {
      source.close();
      eventSourcesRef.current.delete(assistantId);

      void retrieveFailedJob(
        assistantId,
        jobId,
        payload.message || "Research execution failed.",
      );

      void refreshConversationList();
    });
  }

  async function openConversation(id: string) {
    if (sending || loadingConversationId) {
      return;
    }

    const requestSequence = ++conversationLoadSequenceRef.current;

    closeResearchStreams();

    setLoadingConversationId(id);
    setHistoryError("");

    try {
      const conversation = await researchApi.getConversation(id);

      // Ignore stale responses if the user has changed the active request.
      if (requestSequence !== conversationLoadSequenceRef.current) {
        return;
      }

      const restoredMessages = toChatMessages(conversation.jobs);

      // Make restored assistant messages available to SSE handlers
      // immediately, before React commits the next render.
      messagesRef.current = new Map(
        restoredMessages
          .filter(
            (message): message is AssistantMessage =>
              message.role === "assistant",
          )
          .map((message) => [message.id, message]),
      );

      setMessages(restoredMessages);
      setConversationId(conversation.id);
      setPrompt("");
      setComposerError("");
      setMobileSidebarOpen(false);

      // Reconnect to jobs that are still running.
      for (const job of conversation.jobs) {
        if (job.status === "queued" || job.status === "running") {
          connectToResearchEvents(
            job.job_id,
            job.job_id,
            researchApi.jobEventsUrl(job.job_id),
          );
        }
      }
    } catch (error) {
      if (requestSequence === conversationLoadSequenceRef.current) {
        setHistoryError(
          error instanceof Error
            ? error.message
            : "Unable to open this conversation.",
        );
      }
    } finally {
      if (requestSequence === conversationLoadSequenceRef.current) {
        setLoadingConversationId(null);
      }
    }
  }

  async function handleSend() {
    const question = prompt.trim();

    if (!question || sending || loadingConversationId) {
      return;
    }

    if (question.length < 10) {
      setComposerError("Please enter at least 10 characters.");
      return;
    }

    setComposerError("");

    const userMessage: UserMessage = {
      id: createId(),
      role: "user",
      content: question,
    };

    const assistantMessage: AssistantMessage = {
      id: createId(),
      role: "assistant",
      status: "submitting",
      progress: [],
      statusMessage: "Submitting your research question...",
      connection: "connecting",
    };

    messagesRef.current.set(
      assistantMessage.id,
      assistantMessage,
    );

    setMessages((current) => [
      ...current,
      userMessage,
      assistantMessage,
    ]);

    setPrompt("");
    setSending(true);

    try {
      const accepted = await researchApi.submit({
        question,
        conversation_id: conversationId ?? undefined,
        requested_sources: ["internal"],
      });

      setConversationId(accepted.conversation_id);

      updateAssistant(assistantMessage.id, {
        status: "queued",
        jobId: accepted.job_id,
        statusMessage: "Research job accepted and queued.",
      });

      void refreshConversationList();

      connectToResearchEvents(
        assistantMessage.id,
        accepted.job_id,
        accepted.events_url,
      );
    } catch (error) {
      updateAssistant(assistantMessage.id, {
        status: "failed",

        error:
          error instanceof Error
            ? error.message
            : "Unable to submit the research question.",

        connection: "closed",
      });
    } finally {
      setSending(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void handleSend();
  }

  function handleComposerKeyDown(
    event: KeyboardEvent<HTMLTextAreaElement>,
  ) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void handleSend();
    }
  }

  async function handleLogout() {
    setLoggingOut(true);
    setLogoutError("");

    closeResearchStreams();

    try {
      await logout();
      navigate("/login", {
        replace: true,
      });
    } catch (error) {
      setLogoutError(
        error instanceof Error
          ? error.message
          : "Unable to sign out.",
      );

      setLoggingOut(false);
    }
  }

  function renderAssistantMessage(message: AssistantMessage) {
    const isActive =
      message.status === "submitting" ||
      message.status === "queued" ||
      message.status === "running";

    return (
      <article
        className="chat-assistant-message"
        key={message.id}
      >
        <div className="chat-assistant-avatar">
          <Sparkles size={17} />
        </div>

        <div className="chat-assistant-content">
          <div className="chat-assistant-heading">
            <strong>ASYNC RESEARCH AGENT</strong>

            <span
              className={`chat-result-status ${message.status}`}
            >
              {message.status === "submitting" && "Submitting"}
              {message.status === "queued" && "Queued"}
              {message.status === "running" && "Researching"}
              {message.status === "completed" && "Completed"}
              {message.status === "failed" && "Failed"}
            </span>
          </div>

          {isActive && (
            <div className="chat-execution-card">
              <div className="chat-execution-header">
                <span className="chat-execution-indicator">
                  <LoaderCircle size={15} />
                </span>

                <div>
                  <strong>
                    {message.status === "queued"
                      ? "Waiting for a worker"
                      : message.status === "submitting"
                        ? "Sending research request"
                        : "Research in progress"}
                  </strong>

                  <span>
                    {message.statusMessage ||
                      "Preparing your research workflow."}
                  </span>
                </div>
              </div>

              {message.progress.length > 0 && (
                <div className="chat-progress-list">
                  {message.progress.map((item, index) => (
                    <div
                      className="chat-progress-item"
                      key={`${message.id}-${index}`}
                    >
                      <CheckCircle2 size={15} />

                      <div>
                        <strong>{formatStage(item.stage)}</strong>
                        <span>{item.message}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {message.connection === "reconnecting" && (
                <div className="chat-connection-notice">
                  Reconnecting to live research updates. The backend job
                  continues independently.
                </div>
              )}
            </div>
          )}

          {message.status === "completed" && (
            <>
              {message.report ? (
                <div className="chat-report">
                  <div className="chat-report-heading">
                    <CheckCircle2 size={17} />
                    Research report
                  </div>

                  <div className="chat-markdown">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {message.report}
                    </ReactMarkdown>
                  </div>
                </div>
              ) : (
                <div
                  className="chat-report-error"
                  role="alert"
                >
                  <CircleAlert size={16} />

                  {message.reportError ||
                    "The research completed, but the report is not available."}
                </div>
              )}
            </>
          )}

          {message.status === "failed" && (
            <div
              className="chat-research-error"
              role="alert"
            >
              <CircleAlert size={17} />

              <div>
                <strong>Research could not be completed</strong>

                <span>
                  {message.error || "An unexpected error occurred."}
                </span>
              </div>
            </div>
          )}
        </div>
      </article>
    );
  }

  return (
    <div
      className={`chat-app ${sidebarCollapsed ? "is-collapsed" : ""} ${
        mobileSidebarOpen ? "mobile-sidebar-open" : ""
      }`}
    >
      {mobileSidebarOpen && (
        <button
          type="button"
          className="chat-sidebar-backdrop"
          aria-label="Close sidebar"
          onClick={() => setMobileSidebarOpen(false)}
        />
      )}

      <aside className="chat-sidebar">
        <div className="chat-sidebar-header">
          <div className="chat-brand">
            <span className="chat-brand-icon">
              <Activity size={20} />
            </span>

            <span className="chat-brand-copy">
              <strong>ASYNC</strong>
              <small>MARKET INTELLIGENCE</small>
            </span>
          </div>

          <button
            type="button"
            className="chat-mobile-close"
            onClick={() => setMobileSidebarOpen(false)}
            aria-label="Close sidebar"
          >
            <X size={18} />
          </button>
        </div>

        <button
          type="button"
          className="chat-new-button"
          onClick={startNewChat}
          disabled={sending || loadingConversationId !== null}
        >
          <Plus size={18} />
          <span>New chat</span>
        </button>

        <label className="chat-sidebar-search">
          <Search size={16} />

          <input
            type="search"
            placeholder="Search conversations"
            aria-label="Search conversations"
            value={historyQuery}
            onChange={(event) => setHistoryQuery(event.target.value)}
          />
        </label>

        <div className="chat-sidebar-section">
          <div className="chat-sidebar-section-heading">
            YOUR CONVERSATIONS
          </div>

          {historyLoading && conversations.length === 0 && (
            <div className="chat-history-feedback">
              Loading conversations...
            </div>
          )}

          {historyError && (
            <div
              className="chat-history-feedback"
              role="alert"
            >
              {historyError}
            </div>
          )}

          {!historyLoading && filteredConversations.length === 0 && (
            <div className="chat-empty-history">
              <span className="chat-empty-icon">
                <MessageSquare size={19} />
              </span>

              <strong>
                {historyQuery.trim()
                  ? "No matching conversations"
                  : "No conversations yet"}
              </strong>

              <span>
                {historyQuery.trim()
                  ? "Try a different search term."
                  : "Your saved research sessions will appear here."}
              </span>
            </div>
          )}

          {filteredConversations.length > 0 && (
            <div className="chat-history-list">
              {filteredConversations.map((conversation) => (
                <button
                  key={conversation.id}
                  type="button"
                  className={`chat-history-item ${
                    conversation.id === conversationId ? "active" : ""
                  }`}
                  onClick={() => void openConversation(conversation.id)}
                  disabled={sending || loadingConversationId !== null}
                  title={conversation.title}
                  aria-current={
                    conversation.id === conversationId
                      ? "page"
                      : undefined
                  }
                >
                  {loadingConversationId === conversation.id ? (
                    <LoaderCircle
                      size={15}
                      className="chat-history-loading"
                    />
                  ) : (
                    <MessageSquare size={15} />
                  )}

                  <span>{conversation.title}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="chat-sidebar-spacer" />

        <div className="chat-sidebar-footer">
          <div className="chat-privacy">
            <ShieldCheck size={16} />
            <span>Private workspace</span>
          </div>

          <div className="chat-user">
            <div className="chat-avatar">
              {initials || "U"}
            </div>

            <div className="chat-user-details">
              <strong>{displayName}</strong>
              <span>{email}</span>
            </div>

            <button
              type="button"
              className="chat-logout"
              onClick={handleLogout}
              disabled={loggingOut}
              aria-label="Sign out"
              title="Sign out"
            >
              <LogOut size={17} />
            </button>
          </div>

          {logoutError && (
            <p className="chat-error" role="alert">
              {logoutError}
            </p>
          )}
        </div>
      </aside>

      <main className="chat-main">
        <header className="chat-topbar">
          <div className="chat-topbar-left">
            <button
              type="button"
              className="chat-desktop-toggle"
              onClick={() =>
                setSidebarCollapsed((value) => !value)
              }
              aria-label="Toggle sidebar"
            >
              {sidebarCollapsed ? (
                <PanelLeftOpen size={19} />
              ) : (
                <PanelLeftClose size={19} />
              )}
            </button>

            <button
              type="button"
              className="chat-mobile-toggle"
              onClick={() => setMobileSidebarOpen(true)}
              aria-label="Open sidebar"
            >
              <Menu size={20} />
            </button>

            <span className="chat-topbar-divider" />

            <div className="chat-current-workspace">
              <span className="chat-workspace-icon">
                <Sparkles size={15} />
              </span>

              <span>Research assistant</span>
            </div>
          </div>

          <div className="chat-topbar-right">
            <span className="chat-engine-status">
              <span className="chat-status-dot" />
              Live research
            </span>
          </div>
        </header>

        <section
          className={`chat-stage ${
            messages.length > 0 ? "has-messages" : ""
          }`}
        >
          <div className="chat-ambient-glow chat-ambient-one" />
          <div className="chat-ambient-glow chat-ambient-two" />

          {messages.length === 0 ? (
            <div className="chat-welcome">
              <div className="chat-welcome-icon">
                <Sparkles size={22} />
              </div>

              <div className="chat-welcome-eyebrow">
                YOUR AI RESEARCH ASSISTANT
              </div>

              <h1>
                Think deeper.
                <br />
                <span>Discover more.</span>
              </h1>

              <p className="chat-welcome-description">
                Ask complex questions about your business, datasets and
                markets. Bring together quantitative analysis and external
                research to find answers backed by evidence.
              </p>

              <div className="chat-suggestion-heading">
                <span>START WITH A RESEARCH IDEA</span>
                <span className="chat-suggestion-line" />
              </div>

              <div className="chat-suggestion-grid">
                {suggestions.map((suggestion) => {
                  const Icon = suggestion.icon;

                  return (
                    <button
                      type="button"
                      key={suggestion.title}
                      className="chat-suggestion-card"
                      onClick={() =>
                        selectSuggestion(suggestion.prompt)
                      }
                    >
                      <div className="chat-suggestion-card-top">
                        <span className="chat-suggestion-icon">
                          <Icon size={19} />
                        </span>

                        <span className="chat-suggestion-category">
                          {suggestion.category}
                        </span>
                      </div>

                      <strong>{suggestion.title}</strong>

                      <span className="chat-suggestion-description">
                        {suggestion.description}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="chat-thread">
              {messages.map((message) =>
                message.role === "user" ? (
                  <article
                    className="chat-user-message"
                    key={message.id}
                  >
                    <div className="chat-user-message-bubble">
                      {message.content}
                    </div>

                    <div className="chat-user-message-avatar">
                      {initials || "U"}
                    </div>
                  </article>
                ) : (
                  renderAssistantMessage(message)
                ),
              )}

              <div ref={bottomRef} />
            </div>
          )}

          <div className="chat-composer-area">
            {composerError && (
              <div className="chat-notice" role="alert">
                {composerError}
              </div>
            )}

            {loadingConversationId && (
              <div className="chat-notice" role="status">
                <LoaderCircle
                  size={14}
                  className="chat-history-loading"
                />

                Loading saved conversation...
              </div>
            )}

            <form
              className="chat-composer"
              onSubmit={handleSubmit}
            >
              <div className="chat-composer-top">
                <span className="chat-composer-label">
                  <span className="chat-composer-label-dot" />
                  MESSAGE ASYNC
                </span>

                <span className="chat-composer-hint">
                  Research with data and evidence
                </span>
              </div>

              <textarea
                ref={promptRef}
                value={prompt}
                onChange={(event) => {
                  setPrompt(event.target.value);
                  setComposerError("");
                }}
                onKeyDown={handleComposerKeyDown}
                placeholder="Ask a question, explore a trend or investigate a market..."
                rows={3}
                aria-label="Research question"
                disabled={loadingConversationId !== null}
              />

              <div className="chat-composer-bottom">
                <span className="chat-composer-shortcut">
                  <kbd>Enter</kbd> to send
                  <span>·</span>
                  <kbd>Shift + Enter</kbd> for a new line
                </span>

                <button
                  type="submit"
                  className="chat-send-button"
                  disabled={
                    !prompt.trim() ||
                    sending ||
                    loadingConversationId !== null
                  }
                  aria-label="Send research question"
                  title="Send research question"
                >
                  {sending ? (
                    <LoaderCircle
                      size={18}
                      className="chat-spinner"
                    />
                  ) : (
                    <ArrowUp size={19} />
                  )}
                </button>
              </div>
            </form>

            <div className="chat-disclaimer">
              <ShieldCheck size={13} />
              Research is grounded in available data and cited evidence.
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}