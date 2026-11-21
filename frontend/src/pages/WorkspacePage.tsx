import { ResearchVisualizationsPanel } from "../components/charts/ResearchVisualizations";
import { createPortal } from "react-dom";
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
  Check,
  CheckCircle2,
  CircleAlert,
  Database,
  LoaderCircle,
  LogOut,
  Menu,
  MessageSquare,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  Workflow,
  X,
  Square,
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
  type ResearchVisualizations,
} from "../services/research";
import "./WorkspacePage.css";

interface ProgressItem {
  stage: string;
  message: string;
}

interface ConversationMenuPosition {
  top: number;
  left: number;
}

interface UserMessage {
  id: string;
  role: "user";
  content: string;
  assistantMessageId: string;
}

type ResearchStatus =
  | "submitting"
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

interface AssistantMessage {
  id: string;
  role: "assistant";
  status: ResearchStatus;
  jobId?: string;
  progress: ProgressItem[];
  statusMessage?: string;
  report?: string;
  visualizations?: ResearchVisualizations | null;
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
      assistantMessageId: job.job_id,
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
      visualizations: job.result?.visualizations ?? null,
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

function ConversationTitle({ title }: { title: string }) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLSpanElement>(null);
  const [isOverflowing, setIsOverflowing] = useState(false);

  useEffect(() => {
    const viewport = viewportRef.current;
    const text = textRef.current;

    if (!viewport || !text) {
      return;
    }

    const measure = () => {
      setIsOverflowing(
        text.scrollWidth > viewport.clientWidth + 1,
      );
    };

    measure();

    const observer = new ResizeObserver(measure);

    observer.observe(viewport);
    observer.observe(text);

    return () => observer.disconnect();
  }, [title]);

  return (
    <div
      ref={viewportRef}
      className={`chat-history-title-viewport ${isOverflowing ? "is-overflowing" : ""
        }`}
      title={title}
    >
      <div className="chat-history-title-track">
        <span ref={textRef}>{title}</span>

        {isOverflowing && (
          <span aria-hidden="true">{title}</span>
        )}
      </div>
    </div>
  );
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

  const [openConversationMenuId, setOpenConversationMenuId] =
    useState<string | null>(null);
  const [conversationMenuPosition, setConversationMenuPosition] =
    useState<ConversationMenuPosition | null>(null);
  const [editingConversationId, setEditingConversationId] =
    useState<string | null>(null);
  const [editingConversationTitle, setEditingConversationTitle] = useState("");
  const [savingConversationId, setSavingConversationId] =
    useState<string | null>(null);
  const [deletingConversationId, setDeletingConversationId] =
    useState<string | null>(null);

  const [cancellingAssistantId, setCancellingAssistantId] =
    useState<string | null>(null);

  const [editingUserMessageId, setEditingUserMessageId] =
    useState<string | null>(null);

  const [editingUserMessageDraft, setEditingUserMessageDraft] =
    useState("");

  const [loadingConversationId, setLoadingConversationId] = useState<
    string | null
  >(null);

  const [sending, setSending] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState("");
  const [composerError, setComposerError] = useState("");

  const activeAssistantMessage = [...messages]
    .reverse()
    .find(
      (message): message is AssistantMessage =>
        message.role === "assistant" &&
        (
          message.status === "submitting" ||
          message.status === "queued" ||
          message.status === "running"
        ),
    );

  const hasActiveResearch = Boolean(activeAssistantMessage);

  const promptRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const historyListRef = useRef<HTMLDivElement>(null);

  const eventSourcesRef = useRef<Map<string, EventSource>>(new Map());

  const messagesRef = useRef<Map<string, AssistantMessage>>(new Map());

  const stopRequestedAssistantIdRef = useRef<string | null>(null);

  const conversationLoadSequenceRef = useRef(0);

  const closeConversationMenu = useCallback(() => {
    setOpenConversationMenuId(null);
    setConversationMenuPosition(null);
  }, []);

  function toggleConversationMenu(
    id: string,
    trigger: HTMLButtonElement,
  ) {
    if (openConversationMenuId === id) {
      closeConversationMenu();
      return;
    }

    const rect = trigger.getBoundingClientRect();

    // Keep these dimensions aligned with .chat-history-menu-portal in CSS.
    const MENU_WIDTH = 168;
    const MENU_HEIGHT = 96;
    const GAP = 8;
    const EDGE = 12;

    const spaceBelow = window.innerHeight - rect.bottom - EDGE;
    const spaceAbove = rect.top - EDGE;
    const openAbove =
      spaceBelow < MENU_HEIGHT + GAP && spaceAbove > spaceBelow;

    const preferredTop = openAbove
      ? rect.top - MENU_HEIGHT - GAP
      : rect.bottom + GAP;

    const maxTop = Math.max(EDGE, window.innerHeight - MENU_HEIGHT - EDGE);
    const maxLeft = Math.max(EDGE, window.innerWidth - MENU_WIDTH - EDGE);

    const top = Math.max(
      EDGE,
      Math.min(preferredTop, maxTop),
    );
    const left = Math.max(
      EDGE,
      Math.min(rect.right - MENU_WIDTH, maxLeft),
    );

    setConversationMenuPosition({ top, left });
    setOpenConversationMenuId(id);
  }

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

  const menuConversation =
    conversations.find((conversation) => conversation.id === openConversationMenuId) ??
    null;

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


  // Dismiss the portal menu on outside interaction, Escape, resize, or scroll.
  // There is deliberately no full-screen backdrop: it would intercept wheel
  // and touch scrolling inside the conversation history panel.
  useEffect(() => {
    if (!openConversationMenuId) {
      return;
    }

    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        closeConversationMenu();
      }
    };

    const handleOutsidePointerDown = (event: globalThis.PointerEvent) => {
      const target = event.target;

      if (!(target instanceof Element)) {
        return;
      }

      // Keep the menu open when interacting with its trigger or its portal.
      if (
        target.closest(".chat-history-menu-portal") ||
        target.closest(".chat-history-menu-trigger")
      ) {
        return;
      }

      closeConversationMenu();
    };

    const closeForViewportChange = () => closeConversationMenu();

    const historyList = historyListRef.current;

    document.addEventListener("pointerdown", handleOutsidePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("resize", closeForViewportChange);
    // Capture scroll events from nested scroll containers as well.
    window.addEventListener("scroll", closeForViewportChange, true);
    historyList?.addEventListener("scroll", closeForViewportChange);

    return () => {
      document.removeEventListener("pointerdown", handleOutsidePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("resize", closeForViewportChange);
      window.removeEventListener("scroll", closeForViewportChange, true);
      historyList?.removeEventListener("scroll", closeForViewportChange);
    };
  }, [openConversationMenuId, closeConversationMenu]);

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

    setEditingUserMessageId(null);
    setEditingUserMessageDraft("");
    if (sending) {
      return;
    }

    conversationLoadSequenceRef.current += 1;

    closeResearchStreams();
    closeConversationMenu();
    setEditingConversationId(null);
    setEditingConversationTitle("");

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
      if (job.status === "cancelled") {
        updateAssistant(assistantId, {
          status: "cancelled",
          statusMessage: "Research was cancelled.",
          connection: "closed",
        });

        return;
      }

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

        visualizations: job.result?.visualizations ?? null,

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

    // EventSource automatically sends Last-Event-ID on reconnection.
    // The backend resumes after that Redis Stream event ID.
    // De-duplicate events within this connection as an additional safeguard.
    const seenEventIds = new Set<string>();

    source.onopen = () => {
      console.info("[SSE] Connected", {
        jobId,
        readyState: source.readyState,
      });

      updateAssistant(assistantId, {
        connection: "connected",
      });
    };

    source.onerror = () => {
      console.warn("[SSE] Connection error", {
        jobId,
        readyState: source.readyState,
        reconnecting: source.readyState === EventSource.CONNECTING,
      });

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

    registerEvent("cancelled", (payload) => {
      source.close();
      eventSourcesRef.current.delete(assistantId);

      updateAssistant(assistantId, {
        status: "cancelled",
        statusMessage: payload.message || "Research was cancelled.",
        connection: "closed",
      });

      void refreshConversationList();
    });
  }

  async function openConversation(id: string) {
    setEditingUserMessageId(null);
    setEditingUserMessageDraft("");
    if (sending || loadingConversationId) {
      return;
    }

    closeConversationMenu();
    setEditingConversationId(null);
    setEditingConversationTitle("");

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

  function beginEditUserMessage(message: UserMessage) {
    const assistantMessage = messages.find(
      (item): item is AssistantMessage =>
        item.role === "assistant" &&
        item.id === message.assistantMessageId,
    );

    if (
      !assistantMessage ||
      ["submitting", "queued", "running"].includes(assistantMessage.status) ||
      hasActiveResearch ||
      sending
    ) {
      return;
    }

    setEditingUserMessageId(message.id);
    setEditingUserMessageDraft(message.content);
  }

  function cancelEditUserMessage() {
    setEditingUserMessageId(null);
    setEditingUserMessageDraft("");
  }

  async function cancelAssistantJob(
    assistantId: string,
    jobId: string,
  ) {
    setCancellingAssistantId(assistantId);

    updateAssistant(assistantId, {
      statusMessage: "Cancelling your research request...",
    });

    try {
      const result = await researchApi.cancelJob(jobId);

      if (result.status === "cancelled") {
        eventSourcesRef.current.get(assistantId)?.close();
        eventSourcesRef.current.delete(assistantId);

        updateAssistant(assistantId, {
          status: "cancelled",
          statusMessage: "Research was cancelled.",
          connection: "closed",
        });
      } else if (result.status === "completed") {
        await retrieveCompletedReport(assistantId, jobId);
      } else if (result.status === "failed") {
        await retrieveFailedJob(
          assistantId,
          jobId,
          "Research execution failed.",
        );
      } else {
        updateAssistant(assistantId, {
          status: result.status,
          statusMessage: "Checking the current research status...",
        });
      }

      void refreshConversationList();
    } catch (error) {
      updateAssistant(assistantId, {
        statusMessage:
          error instanceof Error
            ? `Unable to cancel research: ${error.message}`
            : "Unable to cancel research. Please try again.",
      });
    } finally {
      setCancellingAssistantId((current) =>
        current === assistantId ? null : current,
      );
    }
  }

  async function handleStopResearch() {
    const activeMessage = activeAssistantMessage;

    if (!activeMessage || cancellingAssistantId === activeMessage.id) {
      return;
    }

    if (!activeMessage.jobId) {
      // The submission request is still awaiting its job ID.
      // Cancel immediately after the backend accepts it.
      stopRequestedAssistantIdRef.current = activeMessage.id;
      setCancellingAssistantId(activeMessage.id);

      updateAssistant(activeMessage.id, {
        statusMessage: "Cancellation requested...",
      });

      return;
    }

    await cancelAssistantJob(
      activeMessage.id,
      activeMessage.jobId,
    );
  }

  async function submitQuestion(question: string) {
    const normalizedQuestion = question.trim();

    if (
      !normalizedQuestion ||
      sending ||
      loadingConversationId ||
      hasActiveResearch
    ) {
      return;
    }

    setComposerError("");

    const assistantMessage: AssistantMessage = {
      id: createId(),
      role: "assistant",
      status: "submitting",
      progress: [],
      statusMessage: "Submitting your research question...",
      connection: "connecting",
    };

    const userMessage: UserMessage = {
      id: createId(),
      role: "user",
      content: normalizedQuestion,
      assistantMessageId: assistantMessage.id,
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

    setSending(true);

    try {
      const accepted = await researchApi.submit({
        question: normalizedQuestion,
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

      if (
        stopRequestedAssistantIdRef.current === assistantMessage.id
      ) {
        stopRequestedAssistantIdRef.current = null;

        await cancelAssistantJob(
          assistantMessage.id,
          accepted.job_id,
        );
      }
    } catch (error) {
      updateAssistant(assistantMessage.id, {
        status: "failed",
        error:
          error instanceof Error
            ? error.message
            : "Unable to submit the research question.",
        connection: "closed",
      });

      if (
        stopRequestedAssistantIdRef.current === assistantMessage.id
      ) {
        stopRequestedAssistantIdRef.current = null;
        setCancellingAssistantId(null);
      }
    } finally {
      setSending(false);
    }
  }

  async function handleSend() {
    const question = prompt.trim();

    if (!question || sending || loadingConversationId) {
      return;
    }

    setPrompt("");
    await submitQuestion(question);
  }

  async function handleResubmitEditedMessage() {
    const question = editingUserMessageDraft.trim();
    const userMessageId = editingUserMessageId;

    if (
      !question ||
      !userMessageId ||
      sending ||
      loadingConversationId ||
      hasActiveResearch
    ) {
      return;
    }

    const userMessage = messages.find(
      (message): message is UserMessage =>
        message.role === "user" && message.id === userMessageId,
    );

    if (!userMessage) {
      setComposerError("Unable to find the message you want to edit.");
      return;
    }

    const assistantMessage = messages.find(
      (message): message is AssistantMessage =>
        message.role === "assistant" &&
        message.id === userMessage.assistantMessageId,
    );

    if (!assistantMessage?.jobId) {
      setComposerError("Unable to identify the original research job.");
      return;
    }

    const originalQuestion = userMessage.content;
    const previousAssistantMessage = { ...assistantMessage };
    const originalJobId = assistantMessage.jobId;

    setComposerError("");
    setSending(true);

    // Close any remaining stream for the previous, terminal execution.
    eventSourcesRef.current.get(assistantMessage.id)?.close();
    eventSourcesRef.current.delete(assistantMessage.id);

    // Update the existing user message, preserving its ID and position.
    setMessages((current) =>
      current.map((message) =>
        message.role === "user" && message.id === userMessageId
          ? { ...message, content: question }
          : message,
      ),
    );

    // Reset the existing assistant message for the new execution.
    updateAssistant(assistantMessage.id, {
      status: "submitting",
      jobId: undefined,
      progress: [],
      statusMessage: "Submitting your revised research question...",
      report: undefined,
      visualizations: null,
      reportError: undefined,
      error: undefined,
      connection: "connecting",
    });

    try {
      const accepted = await researchApi.reviseJob(
        originalJobId,
        question,
      );

      setConversationId(accepted.conversation_id);

      // Keep the same assistant message ID, but attach the new job ID.
      updateAssistant(assistantMessage.id, {
        status: "queued",
        jobId: accepted.job_id,
        statusMessage: "Revised research job accepted and queued.",
        connection: "connecting",
      });

      cancelEditUserMessage();

      void refreshConversationList();

      connectToResearchEvents(
        assistantMessage.id,
        accepted.job_id,
        accepted.events_url,
      );
    } catch (error) {
      // Restore the original question if the revision was not accepted.
      setMessages((current) =>
        current.map((message) =>
          message.role === "user" && message.id === userMessageId
            ? { ...message, content: originalQuestion }
            : message,
        ),
      );

      // Restore the previous assistant response and status.
      updateAssistant(assistantMessage.id, previousAssistantMessage);

      setComposerError(
        error instanceof Error
          ? error.message
          : "Unable to revise the research question.",
      );
    } finally {
      setSending(false);
    }
  }


  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (hasActiveResearch) {
      void handleStopResearch();
      return;
    }

    void handleSend();
  }
  function handleComposerKeyDown(
    event: KeyboardEvent<HTMLTextAreaElement>,
  ) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();

      if (hasActiveResearch) {
        void handleStopResearch();
        return;
      }

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

  function beginRenameConversation(
    conversation: ResearchConversationSummary,
  ) {
    closeConversationMenu();
    setEditingConversationId(conversation.id);
    setEditingConversationTitle(conversation.title);
    setHistoryError("");
  }

  function cancelRenameConversation() {
    setEditingConversationId(null);
    setEditingConversationTitle("");
    setHistoryError("");
  }

  async function saveRenameConversation(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();

    const id = editingConversationId;
    const title = editingConversationTitle.trim().replace(/\s+/g, " ");

    if (!id) {
      return;
    }

    if (!title) {
      setHistoryError("Please enter a conversation title.");
      return;
    }

    if (title.length > 80) {
      setHistoryError("Conversation titles cannot exceed 80 characters.");
      return;
    }

    setSavingConversationId(id);
    setHistoryError("");

    try {
      const updated = await researchApi.renameConversation(id, title);

      setConversations((current) =>
        current.map((conversation) =>
          conversation.id === id ? updated : conversation,
        ),
      );

      setEditingConversationId(null);
      setEditingConversationTitle("");
    } catch (error) {
      setHistoryError(
        error instanceof Error
          ? error.message
          : "Unable to rename conversation.",
      );
    } finally {
      setSavingConversationId(null);
    }
  }

  async function handleDeleteConversation(
    conversation: ResearchConversationSummary,
  ) {
    closeConversationMenu();

    const confirmed = window.confirm(
      `Delete "${conversation.title}" and all its research history? This action cannot be undone.`,
    );

    if (!confirmed) {
      return;
    }

    const id = conversation.id;

    setDeletingConversationId(id);
    setHistoryError("");

    try {
      await researchApi.deleteConversation(id);

      // Invalidate any pending conversation load before clearing the active view.
      if (conversationId === id || loadingConversationId === id) {
        conversationLoadSequenceRef.current += 1;
      }

      if (conversationId === id) {
        setEditingUserMessageId(null);
        setEditingUserMessageDraft("");
        closeResearchStreams();
        messagesRef.current.clear();
        setMessages([]);
        setConversationId(null);
        setPrompt("");
        setComposerError("");
        setMobileSidebarOpen(false);
      }

      if (loadingConversationId === id) {
        setLoadingConversationId(null);
      }

      setConversations((current) =>
        current.filter((item) => item.id !== id),
      );

      if (editingConversationId === id) {
        setEditingConversationId(null);
        setEditingConversationTitle("");
      }
    } catch (error) {
      setHistoryError(
        error instanceof Error
          ? error.message
          : "Unable to delete conversation.",
      );
    } finally {
      setDeletingConversationId(null);
    }
  }

  function renderAssistantMessage(message: AssistantMessage) {
    const isActive =
      message.status === "submitting" ||
      message.status === "queued" ||
      message.status === "running";

    const hasVisualizations = Boolean(
            (message.visualizations?.charts.length ?? 0) > 0 ||
            (message.visualizations?.warnings.length ?? 0) > 0,
          );

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
              {message.status === "cancelled" && "Cancelled"}
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
              {message.report || hasVisualizations ? (
                <div className="chat-report">
                  <div className="chat-report-heading">
                    <CheckCircle2 size={17} />
                    {message.report
                      ? "Research report"
                      : "Research visualizations"}
                  </div>

                  {message.report && (
                    <div className="chat-markdown">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {message.report}
                      </ReactMarkdown>
                    </div>
                  )}

                  <ResearchVisualizationsPanel
                    visualizations={message.visualizations}
                  />
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
      className={`chat-app ${sidebarCollapsed ? "is-collapsed" : ""} ${mobileSidebarOpen ? "mobile-sidebar-open" : ""
        }`}
    >
      {menuConversation && conversationMenuPosition &&
        createPortal(
          <div
            className="chat-history-menu chat-history-menu-portal"
            role="menu"
            aria-label={`Actions for ${menuConversation.title}`}
            style={{
              top: conversationMenuPosition.top,
              left: conversationMenuPosition.left,
            }}
          >
            <button
              type="button"
              role="menuitem"
              onClick={() => beginRenameConversation(menuConversation)}
            >
              <Pencil size={14} />
              <span>Rename</span>
            </button>

            <button
              type="button"
              role="menuitem"
              className="delete-action"
              onClick={() => void handleDeleteConversation(menuConversation)}
            >
              <Trash2 size={14} />
              <span>Delete</span>
            </button>
          </div>,
          document.body,
        )}

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
            <div className="chat-history-list" ref={historyListRef}>
              {filteredConversations.map((conversation) => {
                const isActive = conversation.id === conversationId;
                const isEditing = conversation.id === editingConversationId;
                const isDeleting = conversation.id === deletingConversationId;
                const isSaving = conversation.id === savingConversationId;
                const menuIsOpen = conversation.id === openConversationMenuId;

                return (
                  <div className="chat-history-row" key={conversation.id}>
                    {isEditing ? (
                      <form
                        className="chat-history-rename-form"
                        onSubmit={(event) => void saveRenameConversation(event)}
                      >
                        <input
                          autoFocus
                          aria-label="Conversation title"
                          maxLength={80}
                          value={editingConversationTitle}
                          disabled={isSaving}
                          onChange={(event) =>
                            setEditingConversationTitle(event.target.value)
                          }
                          onKeyDown={(event) => {
                            if (event.key === "Escape") {
                              cancelRenameConversation();
                            }
                          }}
                        />
                        <button
                          type="submit"
                          title="Save title"
                          aria-label="Save title"
                          disabled={isSaving || !editingConversationTitle.trim()}
                        >
                          {isSaving ? (
                            <LoaderCircle
                              size={14}
                              className="chat-history-loading"
                            />
                          ) : (
                            <Check size={14} />
                          )}
                        </button>
                        <button
                          type="button"
                          title="Cancel rename"
                          aria-label="Cancel rename"
                          onClick={cancelRenameConversation}
                          disabled={isSaving}
                        >
                          <X size={14} />
                        </button>
                      </form>
                    ) : (
                      <>
                        <button
                          type="button"
                          className={`chat-history-item ${isActive ? "active" : ""}`}
                          onClick={() => void openConversation(conversation.id)}
                          disabled={
                            sending ||
                            loadingConversationId !== null ||
                            isDeleting
                          }
                          aria-current={isActive ? "page" : undefined}
                          title={conversation.title}
                        >
                          {loadingConversationId === conversation.id ? (
                            <LoaderCircle
                              size={15}
                              className="chat-history-loading"
                            />
                          ) : (
                            <MessageSquare size={15} />
                          )}
                          <ConversationTitle title={conversation.title} />
                        </button>

                        <div className="chat-history-menu-wrap">
                          <button
                            type="button"
                            className="chat-history-menu-trigger"
                            aria-label={`Actions for ${conversation.title}`}
                            aria-haspopup="menu"
                            aria-expanded={menuIsOpen}
                            disabled={isDeleting}
                            onClick={(event) =>
                              toggleConversationMenu(
                                conversation.id,
                                event.currentTarget,
                              )
                            }
                          >
                            {isDeleting ? (
                              <LoaderCircle
                                size={15}
                                className="chat-history-loading"
                              />
                            ) : (
                              <MoreHorizontal size={17} />
                            )}
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                );
              })}
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
          className={`chat-stage ${messages.length > 0 ? "has-messages" : ""
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
              {messages.map((message) => {
                if (message.role === "assistant") {
                  return renderAssistantMessage(message);
                }

                const assistantMessage = messages.find(
                  (item): item is AssistantMessage =>
                    item.role === "assistant" &&
                    item.id === message.assistantMessageId,
                );

                const isEditing = editingUserMessageId === message.id;

                const canEdit =
                  Boolean(assistantMessage) &&
                  ["completed", "failed", "cancelled"].includes(
                    assistantMessage?.status ?? "",
                  ) &&
                  !hasActiveResearch &&
                  !sending;

                return (
                  <article
                    className="chat-user-message"
                    key={message.id}
                  >
                    <div className="chat-user-message-main">
                      {isEditing ? (
                        <div className="chat-user-message-editor">
                          <textarea
                            value={editingUserMessageDraft}
                            onChange={(event) =>
                              setEditingUserMessageDraft(event.target.value)
                            }
                            onKeyDown={(event) => {
                              if (
                                event.key === "Enter" &&
                                !event.shiftKey
                              ) {
                                event.preventDefault();
                                void handleResubmitEditedMessage();
                              }
                            }}
                            rows={3}
                            maxLength={5000}
                            aria-label="Edit your research question"
                            autoFocus
                          />

                          <div className="chat-user-message-edit-actions">
                            <button
                              type="button"
                              className="chat-message-cancel-button"
                              onClick={cancelEditUserMessage}
                              disabled={sending}
                            >
                              <X size={14} />
                              Cancel
                            </button>

                            <button
                              type="button"
                              className="chat-message-send-button"
                              onClick={() =>
                                void handleResubmitEditedMessage()
                              }
                              disabled={
                                !editingUserMessageDraft.trim() ||
                                sending ||
                                hasActiveResearch
                              }
                            >
                              {sending ? (
                                <LoaderCircle
                                  size={14}
                                  className="chat-spinner"
                                />
                              ) : (
                                <ArrowUp size={14} />
                              )}
                              Send
                            </button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <div className="chat-user-message-bubble">
                            {message.content}
                          </div>

                          {canEdit && (
                            <button
                              type="button"
                              className="chat-user-message-edit-trigger"
                              onClick={() => beginEditUserMessage(message)}
                              aria-label="Edit message"
                              title="Edit message"
                            >
                              <Pencil size={13} />
                              Edit
                            </button>
                          )}
                        </>
                      )}
                    </div>

                    <div className="chat-user-message-avatar">
                      {initials || "U"}
                    </div>
                  </article>
                );
              })}

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
                  className={`chat-send-button ${hasActiveResearch ? "is-stop" : ""
                    }`}
                  disabled={
                    loadingConversationId !== null ||
                    (
                      hasActiveResearch
                        ? cancellingAssistantId === activeAssistantMessage?.id
                        : !prompt.trim() || sending
                    )
                  }
                  aria-label={
                    hasActiveResearch
                      ? "Stop research"
                      : "Send research question"
                  }
                  title={
                    hasActiveResearch
                      ? "Stop research"
                      : "Send research question"
                  }
                >
                  {cancellingAssistantId === activeAssistantMessage?.id &&
                    hasActiveResearch ? (
                    <LoaderCircle size={18} className="chat-spinner" />
                  ) : hasActiveResearch ? (
                    <Square size={16} fill="currentColor" />
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
