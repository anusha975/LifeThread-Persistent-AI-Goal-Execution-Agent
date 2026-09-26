import React, { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  BookOpen,
  Brain,
  CheckCircle2,
  Clock,
  Compass,
  ExternalLink,
  Filter,
  Info,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Sliders,
  Target,
  Trash2,
  X,
} from "lucide-react";
import { memoryService } from "../services/memoryService";
import { goalService } from "../services/goalService";
import {
  MemoryCategory,
  MemoryCorrectionPayload,
  MemoryCreatePayload,
  UserMemoryItem,
} from "../types/memory";
import { formatRelativeTime } from "../utils/dashboardMetrics";
import { Button } from "../components/ui/Button";
import { Modal } from "../components/ui/Modal";
import { Skeleton } from "../components/ui/Skeleton";
import { Alert } from "../components/ui/Alert";
import { EmptyState } from "../components/ui/EmptyState";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";

const CATEGORIES: {
  key: MemoryCategory | "all";
  label: string;
  icon: React.ReactNode;
}[] = [
  { key: "all", label: "All Memories", icon: <Brain className="w-4 h-4" /> },
  {
    key: "Goal memory",
    label: "Goal memory",
    icon: <Target className="w-4 h-4" />,
  },
  {
    key: "Preference",
    label: "Preference",
    icon: <Sliders className="w-4 h-4" />,
  },
  {
    key: "Past outcome",
    label: "Past outcome",
    icon: <CheckCircle2 className="w-4 h-4" />,
  },
  {
    key: "Learned weakness",
    label: "Learned weakness",
    icon: <AlertTriangle className="w-4 h-4" />,
  },
  {
    key: "Relevant knowledge",
    label: "Relevant knowledge",
    icon: <BookOpen className="w-4 h-4" />,
  },
];

export const MemoryContextPage: React.FC = () => {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();

  // Active filter state
  const activeCategory =
    (searchParams.get("category") as MemoryCategory) || undefined;
  const activeGoalId = searchParams.get("goal_id") || undefined;
  const [searchQuery, setSearchQuery] = useState("");

  // Modals state
  const [inspectItem, setInspectItem] = useState<UserMemoryItem | null>(null);
  const [editingItem, setEditingItem] = useState<UserMemoryItem | null>(null);
  const [deletingItem, setDeletingItem] = useState<UserMemoryItem | null>(null);
  const [isCreateOpen, setIsCreateOpen] = useState(false);

  // Form states for Correction
  const [correctedText, setCorrectedText] = useState("");
  const [correctedConfidence, setCorrectedConfidence] = useState(1.0);
  const [correctedCategory, setCorrectedCategory] =
    useState<MemoryCategory>("Goal memory");
  const [editError, setEditError] = useState<string | null>(null);

  // Form states for New Memory
  const [newContent, setNewContent] = useState("");
  const [newCategory, setNewCategory] = useState<MemoryCategory>("Preference");
  const [newConfidence, setNewConfidence] = useState(1.0);
  const [newGoalId, setNewGoalId] = useState<string>("");
  const [createError, setCreateError] = useState<string | null>(null);

  // 1. Fetch Memories from real backend API
  const {
    data: memoryData,
    isLoading: isLoadingMemories,
    isError: isMemoryError,
    refetch: refetchMemories,
    isFetching: isFetchingMemories,
  } = useQuery({
    queryKey: ["memories", activeCategory, activeGoalId, searchQuery],
    queryFn: () =>
      memoryService.listMemories({
        category: activeCategory,
        goalId: activeGoalId,
        query: searchQuery.trim() || undefined,
        limit: 100,
      }),
  });

  // 2. Fetch User Goals for linkage filter and assignment
  const { data: goalsData } = useQuery({
    queryKey: ["goalsSimpleList"],
    queryFn: () => goalService.listGoals({ limit: 100 }),
  });

  // Mutations
  const correctMutation = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: MemoryCorrectionPayload;
    }) => memoryService.correctMemory(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["memories"] });
      setEditingItem(null);
      setEditError(null);
    },
    onError: (err: any) => {
      setEditError(err?.message || "Failed to update memory");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => memoryService.deleteMemory(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["memories"] });
      setDeletingItem(null);
    },
  });

  const createMutation = useMutation({
    mutationFn: (payload: MemoryCreatePayload) =>
      memoryService.createMemory(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["memories"] });
      setIsCreateOpen(false);
      setNewContent("");
      setCreateError(null);
    },
    onError: (err: any) => {
      setCreateError(err?.message || "Failed to create memory");
    },
  });

  // Trigger modal handlers
  const handleOpenEdit = (mem: UserMemoryItem) => {
    setEditingItem(mem);
    setCorrectedText(mem.memory);
    setCorrectedConfidence(mem.confidence);
    setCorrectedCategory(mem.category);
    setEditError(null);
  };

  const handleSaveCorrection = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingItem) return;
    if (!correctedText.trim()) {
      setEditError("Memory statement cannot be empty");
      return;
    }
    correctMutation.mutate({
      id: editingItem.id,
      payload: {
        content: correctedText.trim(),
        confidence: correctedConfidence,
        category: correctedCategory,
      },
    });
  };

  const handleCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newContent.trim()) {
      setCreateError("Memory text is required");
      return;
    }
    createMutation.mutate({
      content: newContent.trim(),
      category: newCategory,
      confidence: newConfidence,
      goal_id: newGoalId || undefined,
    });
  };

  const handleCategorySelect = (catKey: MemoryCategory | "all") => {
    const params = new URLSearchParams(searchParams);
    if (catKey === "all") {
      params.delete("category");
    } else {
      params.set("category", catKey);
    }
    setSearchParams(params);
  };

  const handleGoalSelect = (goalId: string) => {
    const params = new URLSearchParams(searchParams);
    if (!goalId) {
      params.delete("goal_id");
    } else {
      params.set("goal_id", goalId);
    }
    setSearchParams(params);
  };

  const memories = memoryData?.items || [];
  const categoryCounts = memoryData?.category_counts || {};
  const totalCount = memoryData?.total || 0;
  const goals = goalsData?.items || [];

  // Helper badges for category styling
  const getCategoryTheme = (cat: MemoryCategory) => {
    switch (cat) {
      case "Goal memory":
        return {
          border: "border-emerald-500/30",
          bg: "bg-emerald-500/10 text-emerald-400",
          badge: "success" as const,
          icon: <Target className="w-3.5 h-3.5" />,
        };
      case "Preference":
        return {
          border: "border-purple-500/30",
          bg: "bg-purple-500/10 text-purple-400",
          badge: "secondary" as const,
          icon: <Sliders className="w-3.5 h-3.5" />,
        };
      case "Past outcome":
        return {
          border: "border-sky-500/30",
          bg: "bg-sky-500/10 text-sky-400",
          badge: "info" as const,
          icon: <CheckCircle2 className="w-3.5 h-3.5" />,
        };
      case "Learned weakness":
        return {
          border: "border-amber-500/30",
          bg: "bg-amber-500/10 text-amber-400",
          badge: "warning" as const,
          icon: <AlertTriangle className="w-3.5 h-3.5" />,
        };
      case "Relevant knowledge":
        return {
          border: "border-indigo-500/30",
          bg: "bg-indigo-500/10 text-indigo-400",
          badge: "outline" as const,
          icon: <BookOpen className="w-3.5 h-3.5" />,
        };
    }
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-300 pb-16">
      {/* ========================================================================= */}
      {/* 1. SITUATION BANNER & CONTROLS                                            */}
      {/* ========================================================================= */}
      <section
        aria-label="Memory Center Header"
        className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-slate-900 via-slate-900/95 to-slate-950 border border-slate-800 shadow-2xl p-6 sm:p-8"
      >
        <div className="relative z-10 space-y-6">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-slate-800/80">
            <div className="space-y-1">
              <div className="flex items-center space-x-2">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                <span className="text-xs font-mono uppercase tracking-widest text-emerald-400 font-semibold">
                  Autonomous Context & Memory Engine
                </span>
                {isFetchingMemories && (
                  <span className="text-[11px] text-slate-500 font-mono flex items-center space-x-1">
                    <RefreshCw className="w-3 h-3 animate-spin" />
                    <span>Syncing...</span>
                  </span>
                )}
              </div>
              <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight flex items-center space-x-2">
                <span>LifeThread Memory Workspace</span>
              </h1>
              <p className="text-xs sm:text-sm text-slate-400 max-w-2xl">
                Transparent view of what LifeThread has remembered about your
                goals, habits, past outcomes, and learned weaknesses. You
                maintain full sovereignty to audit, correct, or delete any
                memory.
              </p>
            </div>

            <div className="flex items-center space-x-3 shrink-0">
              <button
                onClick={() => refetchMemories()}
                className="p-2 rounded-lg bg-slate-800/60 hover:bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-700/60 transition-colors"
                title="Refresh memories"
                aria-label="Refresh memories"
              >
                <RefreshCw
                  className={`w-4 h-4 ${isFetchingMemories ? "animate-spin" : ""}`}
                />
              </button>
              <Button
                onClick={() => {
                  setNewContent("");
                  setCreateError(null);
                  setIsCreateOpen(true);
                }}
                leftIcon={<Plus className="w-4 h-4" />}
                size="sm"
              >
                Add Memory
              </Button>
            </div>
          </div>

          {/* 5 Category Metric Counters */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            {CATEGORIES.filter((c) => c.key !== "all").map((cat) => {
              const count = categoryCounts[cat.key] || 0;
              const isSelected = activeCategory === cat.key;
              const theme = getCategoryTheme(cat.key as MemoryCategory);

              return (
                <button
                  key={cat.key}
                  onClick={() => handleCategorySelect(cat.key)}
                  className={`p-3.5 rounded-xl border text-left transition-all ${
                    isSelected
                      ? "bg-slate-800/80 border-emerald-500/60 shadow-lg shadow-emerald-500/10 ring-1 ring-emerald-500/30"
                      : "bg-slate-950/60 border-slate-800 hover:border-slate-700 hover:bg-slate-900/60"
                  }`}
                >
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span className="truncate">{cat.label}</span>
                    <span className={theme.bg}>{cat.icon}</span>
                  </div>
                  <div className="text-xl font-bold font-mono text-white mt-1.5">
                    {count}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 2. SEARCH, CATEGORY TABS & GOAL FILTER BAR                                */}
      {/* ========================================================================= */}
      <div className="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-4">
        {/* Category Pills */}
        <div className="flex items-center space-x-1.5 overflow-x-auto pb-2 md:pb-0 scrollbar-thin">
          {CATEGORIES.map((cat) => {
            const isSelected =
              (!activeCategory && cat.key === "all") ||
              activeCategory === cat.key;
            const count =
              cat.key === "all" ? totalCount : categoryCounts[cat.key] || 0;

            return (
              <button
                key={cat.key}
                onClick={() => handleCategorySelect(cat.key)}
                className={`flex items-center space-x-2 px-3.5 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors border ${
                  isSelected
                    ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40 shadow-sm"
                    : "bg-slate-900/60 text-slate-400 border-slate-800 hover:bg-slate-850 hover:text-slate-200"
                }`}
              >
                {cat.icon}
                <span>{cat.label}</span>
                <span
                  className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono ${
                    isSelected
                      ? "bg-emerald-500/30 text-emerald-200"
                      : "bg-slate-800 text-slate-400"
                  }`}
                >
                  {count}
                </span>
              </button>
            );
          })}
        </div>

        {/* Search & Filter Right Block */}
        <div className="flex items-center space-x-3 shrink-0">
          <div className="relative w-full sm:w-64">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search memories..."
              className="w-full bg-slate-900/80 border border-slate-800 rounded-lg pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-emerald-500 transition-colors"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {/* Goal Linkage Dropdown */}
          <div className="relative">
            <select
              value={activeGoalId || ""}
              onChange={(e) => handleGoalSelect(e.target.value)}
              className="bg-slate-900/80 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-emerald-500 appearance-none pr-8 cursor-pointer"
            >
              <option value="">All Linked Goals</option>
              {goals.map((g) => (
                <option key={g.id} value={g.id}>
                  Goal: {g.title.slice(0, 24)}...
                </option>
              ))}
            </select>
            <Filter className="w-3 h-3 text-slate-400 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
          </div>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 3. MEMORIES GRID & CARDS                                                  */}
      {/* ========================================================================= */}
      {isLoadingMemories ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div
              key={i}
              className="p-5 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-3"
            >
              <div className="flex justify-between items-center">
                <Skeleton className="h-5 w-24" />
                <Skeleton className="h-5 w-16" />
              </div>
              <Skeleton className="h-12 w-full" />
              <div className="flex justify-between items-center pt-2">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-4 w-20" />
              </div>
            </div>
          ))}
        </div>
      ) : isMemoryError ? (
        <div className="p-5 rounded-2xl bg-rose-500/10 border border-rose-500/20 text-center space-y-3">
          <div className="w-10 h-10 rounded-full bg-rose-500/20 text-rose-400 flex items-center justify-center mx-auto">
            <AlertTriangle className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white">
              Failed to retrieve memories
            </h3>
            <p className="text-xs text-rose-300/80 max-w-md mx-auto mt-1">
              Unable to load persisted memory vectors from backend services.
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetchMemories()}
            leftIcon={<RefreshCw className="w-3.5 h-3.5" />}
          >
            Retry Connection
          </Button>
        </div>
      ) : memories.length === 0 ? (
        <EmptyState
          icon={Brain}
          title="No Persisted Memories Found"
          description={
            searchQuery || activeCategory || activeGoalId
              ? "No memories match your active filter or search query."
              : "As you decompose goals, complete tasks, or run autonomous learning loops, memories will be securely recorded here."
          }
          action={
            searchQuery || activeCategory || activeGoalId
              ? {
                  label: "Reset Filters",
                  onClick: () => {
                    setSearchQuery("");
                    setSearchParams({});
                  },
                }
              : {
                  label: "Add Manual Memory",
                  icon: Plus,
                  onClick: () => setIsCreateOpen(true),
                }
          }
          secondaryAction={
            searchQuery || activeCategory || activeGoalId
              ? {
                  label: "Add Manual Memory",
                  onClick: () => setIsCreateOpen(true),
                }
              : undefined
          }
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {memories.map((mem) => {
            const theme = getCategoryTheme(mem.category);
            const confidencePercent = Math.round(mem.confidence * 100);

            return (
              <div
                key={mem.id}
                className="group relative rounded-2xl border border-slate-800 hover:border-slate-700 bg-slate-900/60 hover:bg-slate-900/90 transition-all p-5 flex flex-col justify-between shadow-lg hover:shadow-slate-950/60 space-y-4"
              >
                {/* Header: Category Badge + Status / Qualifier */}
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center space-x-2">
                    <span
                      className={`inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-md text-xs font-semibold border ${theme.bg} ${theme.border}`}
                    >
                      {theme.icon}
                      <span>{mem.category}</span>
                    </span>

                    {mem.source_details?.user_corrected && (
                      <span className="text-[10px] font-mono font-medium px-2 py-0.5 rounded bg-emerald-950/60 text-emerald-400 border border-emerald-800/50 flex items-center space-x-1">
                        <Pencil className="w-2.5 h-2.5" />
                        <span>User-Corrected</span>
                      </span>
                    )}

                    {mem.source_details?.is_hypothesis &&
                      !mem.source_details?.user_corrected && (
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-950/60 text-amber-400 border border-amber-800/50">
                          Provisional
                        </span>
                      )}
                  </div>

                  {/* Confidence Meter Badge */}
                  <div
                    className="flex items-center space-x-1.5 text-xs font-mono font-semibold"
                    title={`Confidence score: ${(mem.confidence * 100).toFixed(1)}%`}
                  >
                    <span className="text-slate-400 text-[11px]">Cert:</span>
                    <span
                      className={
                        confidencePercent >= 90
                          ? "text-emerald-400"
                          : confidencePercent >= 70
                            ? "text-sky-400"
                            : "text-amber-400"
                      }
                    >
                      {confidencePercent}%
                    </span>
                  </div>
                </div>

                {/* Primary Memory Statement */}
                <div className="space-y-2">
                  <p className="text-sm font-medium text-slate-100 leading-relaxed break-words">
                    &ldquo;{mem.memory}&rdquo;
                  </p>
                </div>

                {/* Metadata & Provenance Section */}
                <div className="space-y-2 pt-2 border-t border-slate-800/60 text-xs">
                  {/* Related Goal Link */}
                  {mem.related_goal && (
                    <div className="flex items-center space-x-2">
                      <Target className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                      <span className="text-slate-400 shrink-0">Goal:</span>
                      <Link
                        to={`/goals/${mem.related_goal.id}`}
                        className="text-emerald-400 hover:text-emerald-300 font-medium truncate inline-flex items-center space-x-1"
                        title={mem.related_goal.title}
                      >
                        <span className="truncate">
                          {mem.related_goal.title}
                        </span>
                        <ExternalLink className="w-2.5 h-2.5 shrink-0" />
                      </Link>
                    </div>
                  )}

                  {/* Source Provenance */}
                  <div className="flex items-center justify-between text-[11px] text-slate-400">
                    <div className="flex items-center space-x-1.5 truncate max-w-[200px] sm:max-w-xs">
                      <Compass className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                      <span className="text-slate-500">Source:</span>
                      <span
                        className="font-mono text-slate-300 truncate"
                        title={mem.source}
                      >
                        {mem.source_details?.provenance || mem.source}
                      </span>
                    </div>

                    <div className="flex items-center space-x-1 text-slate-500 font-mono">
                      <Clock className="w-3 h-3" />
                      <span title={new Date(mem.created_at).toLocaleString()}>
                        {formatRelativeTime(mem.created_at)}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Card Actions Footer: Inspect Source | Correct Memory | Delete Memory */}
                <div className="flex items-center justify-between pt-3 border-t border-slate-800/80">
                  <button
                    onClick={() => setInspectItem(mem)}
                    className="text-xs font-medium text-slate-400 hover:text-slate-200 inline-flex items-center space-x-1 px-2.5 py-1 rounded-md hover:bg-slate-800/60 transition-colors"
                    title="Inspect Source Provenance"
                  >
                    <Info className="w-3.5 h-3.5 text-slate-400" />
                    <span>Inspect Source</span>
                  </button>

                  <div className="flex items-center space-x-1.5">
                    <button
                      onClick={() => handleOpenEdit(mem)}
                      className="text-xs font-medium text-slate-300 hover:text-white px-2.5 py-1 rounded-md bg-slate-800/60 hover:bg-slate-800 border border-slate-700/60 transition-colors inline-flex items-center space-x-1"
                      title="Correct this memory"
                    >
                      <Pencil className="w-3 h-3 text-emerald-400" />
                      <span>Correct</span>
                    </button>

                    <button
                      onClick={() => setDeletingItem(mem)}
                      className="text-xs p-1.5 rounded-md text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 border border-transparent hover:border-rose-500/20 transition-colors"
                      title="Delete this memory"
                      aria-label="Delete this memory"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ========================================================================= */}
      {/* 4. MODAL: INSPECT SOURCE PROVENANCE                                       */}
      {/* ========================================================================= */}
      {inspectItem && (
        <Modal
          isOpen={Boolean(inspectItem)}
          onClose={() => setInspectItem(null)}
          title="Inspect Memory Source Provenance"
        >
          <div className="space-y-4">
            <div className="p-3.5 rounded-xl bg-slate-950/80 border border-slate-800 space-y-1">
              <span className="text-[10px] font-mono uppercase tracking-wider text-slate-500">
                Memory Statement
              </span>
              <p className="text-sm font-medium text-slate-200 leading-relaxed">
                &ldquo;{inspectItem.memory}&rdquo;
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800 space-y-1">
                <span className="text-slate-500 font-mono">
                  Provenance Origin
                </span>
                <p className="font-semibold text-slate-200">
                  {inspectItem.source}
                </p>
              </div>

              <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800 space-y-1">
                <span className="text-slate-500 font-mono">Category</span>
                <p className="font-semibold text-emerald-400">
                  {inspectItem.category}
                </p>
              </div>

              <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800 space-y-1">
                <span className="text-slate-500 font-mono">
                  Epistemic Status
                </span>
                <p className="font-semibold text-slate-200">
                  {inspectItem.source_details?.epistemic_qualifier ||
                    (inspectItem.source_details?.is_hypothesis
                      ? "Hypothesis"
                      : "Verified Observation")}
                </p>
              </div>

              <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800 space-y-1">
                <span className="text-slate-500 font-mono">
                  Confidence Level
                </span>
                <p className="font-semibold text-white">
                  {(inspectItem.confidence * 100).toFixed(1)}% Certainty
                </p>
              </div>
            </div>

            {inspectItem.source_details?.task_title && (
              <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800 text-xs space-y-1">
                <span className="text-slate-500 font-mono">
                  Originating Task
                </span>
                <p className="text-slate-200 font-medium">
                  {inspectItem.source_details.task_title}
                </p>
              </div>
            )}

            {inspectItem.source_details?.original_content && (
              <div className="p-3 rounded-lg bg-amber-950/20 border border-amber-800/40 text-xs space-y-1">
                <span className="text-amber-400 font-mono font-medium">
                  Original Text Before User Correction
                </span>
                <p className="text-slate-300 italic">
                  &ldquo;{inspectItem.source_details.original_content}&rdquo;
                </p>
              </div>
            )}

            <div className="space-y-1">
              <span className="text-xs font-mono text-slate-400">
                Raw Metadata Attributes
              </span>
              <pre className="p-3 rounded-lg bg-slate-950 border border-slate-800 font-mono text-[11px] text-slate-300 overflow-x-auto max-h-48 scrollbar-thin">
                {JSON.stringify(
                  inspectItem.source_details?.raw_metadata || {},
                  null,
                  2,
                )}
              </pre>
            </div>

            <div className="pt-2 flex justify-end">
              <Button
                onClick={() => setInspectItem(null)}
                variant="outline"
                size="sm"
              >
                Close
              </Button>
            </div>
          </div>
        </Modal>
      )}

      {/* ========================================================================= */}
      {/* 5. MODAL: CORRECT MEMORY                                                  */}
      {/* ========================================================================= */}
      {editingItem && (
        <Modal
          isOpen={Boolean(editingItem)}
          onClose={() => setEditingItem(null)}
          title="Correct Persisted Memory"
        >
          <form onSubmit={handleSaveCorrection} className="space-y-4">
            <p className="text-xs text-slate-400">
              Modify this memory to reflect the accurate truth. LifeThread will
              update its context and mark this entry as user-corrected.
            </p>

            {editError && <Alert variant="error">{editError}</Alert>}

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-slate-300">
                Memory Statement
              </label>
              <textarea
                value={correctedText}
                onChange={(e) => setCorrectedText(e.target.value)}
                rows={3}
                className="w-full bg-slate-900 border border-slate-700/80 rounded-lg p-3 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500"
                placeholder="Enter corrected memory text..."
                required
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-slate-300">
                  Category
                </label>
                <select
                  value={correctedCategory}
                  onChange={(e) =>
                    setCorrectedCategory(e.target.value as MemoryCategory)
                  }
                  className="w-full bg-slate-900 border border-slate-700/80 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
                >
                  <option value="Goal memory">Goal memory</option>
                  <option value="Preference">Preference</option>
                  <option value="Past outcome">Past outcome</option>
                  <option value="Learned weakness">Learned weakness</option>
                  <option value="Relevant knowledge">Relevant knowledge</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-slate-300">
                  Confidence ({Math.round(correctedConfidence * 100)}%)
                </label>
                <input
                  type="range"
                  min="0.1"
                  max="1.0"
                  step="0.05"
                  value={correctedConfidence}
                  onChange={(e) =>
                    setCorrectedConfidence(parseFloat(e.target.value))
                  }
                  className="w-full accent-emerald-500 cursor-pointer mt-2"
                />
              </div>
            </div>

            <div className="pt-3 border-t border-slate-800 flex items-center justify-end space-x-2">
              <Button
                type="button"
                onClick={() => setEditingItem(null)}
                variant="outline"
                size="sm"
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={correctMutation.isPending}
                size="sm"
              >
                {correctMutation.isPending ? "Saving..." : "Save Correction"}
              </Button>
            </div>
          </form>
        </Modal>
      )}

      {/* ========================================================================= */}
      {/* 6. MODAL: DELETE CONFIRMATION                                             */}
      {/* ========================================================================= */}
      <ConfirmDialog
        isOpen={Boolean(deletingItem)}
        onClose={() => setDeletingItem(null)}
        onConfirm={() => deletingItem && deleteMutation.mutate(deletingItem.id)}
        title="Delete Persisted Memory"
        message={
          deletingItem
            ? `Are you sure you want to permanently delete this memory? LifeThread agents will no longer reference it for planning or execution decisions.\n\n"${deletingItem.memory}"`
            : ""
        }
        confirmText="Delete Memory"
        variant="danger"
        isLoading={deleteMutation.isPending}
      />

      {/* ========================================================================= */}
      {/* 7. MODAL: ADD MANUAL MEMORY                                               */}
      {/* ========================================================================= */}
      {isCreateOpen && (
        <Modal
          isOpen={isCreateOpen}
          onClose={() => setIsCreateOpen(false)}
          title="Record Custom Memory"
        >
          <form onSubmit={handleCreateSubmit} className="space-y-4">
            <p className="text-xs text-slate-400">
              Explicitly teach LifeThread a preference, personal work style
              rule, or goal constraint.
            </p>

            {createError && <Alert variant="error">{createError}</Alert>}

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-slate-300">
                Memory Statement
              </label>
              <textarea
                value={newContent}
                onChange={(e) => setNewContent(e.target.value)}
                rows={3}
                className="w-full bg-slate-900 border border-slate-700/80 rounded-lg p-3 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500"
                placeholder="e.g. Always schedule mock interview practice on weekend mornings"
                required
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-slate-300">
                  Category
                </label>
                <select
                  value={newCategory}
                  onChange={(e) =>
                    setNewCategory(e.target.value as MemoryCategory)
                  }
                  className="w-full bg-slate-900 border border-slate-700/80 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
                >
                  <option value="Preference">Preference</option>
                  <option value="Goal memory">Goal memory</option>
                  <option value="Past outcome">Past outcome</option>
                  <option value="Learned weakness">Learned weakness</option>
                  <option value="Relevant knowledge">Relevant knowledge</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-slate-300">
                  Linked Goal (Optional)
                </label>
                <select
                  value={newGoalId}
                  onChange={(e) => setNewGoalId(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700/80 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
                >
                  <option value="">None (Global)</option>
                  {goals.map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.title.slice(0, 24)}...
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-slate-300">
                Confidence ({Math.round(newConfidence * 100)}%)
              </label>
              <input
                type="range"
                min="0.1"
                max="1.0"
                step="0.05"
                value={newConfidence}
                onChange={(e) => setNewConfidence(parseFloat(e.target.value))}
                className="w-full accent-emerald-500 cursor-pointer"
              />
            </div>

            <div className="pt-3 border-t border-slate-800 flex items-center justify-end space-x-2">
              <Button
                type="button"
                onClick={() => setIsCreateOpen(false)}
                variant="outline"
                size="sm"
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={createMutation.isPending}
                size="sm"
              >
                {createMutation.isPending ? "Saving..." : "Add Memory"}
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
};
