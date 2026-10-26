import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useNavigate } from "react-router";
import {
  CalendarDays,
  DoorOpen,
  Users,
  School,
  UsersRound,
  BookOpen,
  ClipboardCheck,
  ExternalLink,
  Layers,
  Sparkles,
  FileText
} from "lucide-react";

import { GooeyInput } from "@/components/ui/gooey-input.jsx";
import { NAV_GROUPS } from "@/components/navigation/nav-config.js";
import { getRooms } from "@/services/api/rooms.js";
import { getFaculty } from "@/services/api/faculty.js";
import { getPrograms } from "@/services/api/programs.js";
import { getEnrollments } from "@/services/api/enrollments.js";
import { getSubjects } from "@/services/api/subjects.js";
import { getAssignments } from "@/services/api/assignments.js";
import { getSpecializations } from "@/services/api/specializations.js";
import { getScheduledClasses } from "@/services/api/schedule.js";
import { cn } from "@/lib/utils.js";
import { INVALIDATION_DOMAINS, subscribeInvalidation } from "@/lib/invalidation.js";

const CATEGORY_CONFIG = {
  navigation: { label: "Pages & Navigation", icon: FileText },
  faculty: { label: "Faculty", icon: Users },
  subjects: { label: "Subjects", icon: BookOpen },
  programs: { label: "Programs & Enrollments", icon: School },
  sections: { label: "Sections", icon: UsersRound },
  assignments: { label: "Teaching Assignments", icon: ClipboardCheck },
  rooms: { label: "Rooms", icon: DoorOpen },
  specializations: { label: "Specializations", icon: Layers },
  scheduled: { label: "Scheduled Classes", icon: CalendarDays },
};

export function UniversalSearchModal({ open, onOpenChange }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [dataCache, setDataCache] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedIndex, setSelectedIndex] = useState(0);

  const resultsListRef = useRef(null);

  // Debounce the query for filtering
  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedQuery(query.trim());
    }, 150);
    return () => clearTimeout(handler);
  }, [query]);

  // Any successful write (new teacher, generated timetable, …) makes the
  // cached search index stale: drop it so the next open reloads.
  useEffect(
    () => subscribeInvalidation(INVALIDATION_DOMAINS, () => setDataCache(null)),
    []
  );

  // Load authoritative data when modal opens if not already cached
  useEffect(() => {
    if (!open) {
      return;
    }

    let isSubscribed = true;
    if (!dataCache) {
      queueMicrotask(() => {
        if (!isSubscribed) return;
        setIsLoading(true);
        setError(null);
      });

      Promise.allSettled([
        getRooms(),
        getFaculty(),
        getPrograms(),
        getEnrollments(),
        getSubjects(),
        getAssignments(),
        getSpecializations(),
        getScheduledClasses(),
      ])
        .then(([roomsRes, facultyRes, programsRes, enrollmentsRes, subjectsRes, assignmentsRes, specsRes, scheduledRes]) => {
          if (!isSubscribed) return;

          const rooms = roomsRes.status === "fulfilled" ? roomsRes.value : [];
          const faculty = facultyRes.status === "fulfilled" ? facultyRes.value : [];
          const programs = programsRes.status === "fulfilled" ? programsRes.value : [];
          const enrollmentsData = enrollmentsRes.status === "fulfilled" ? enrollmentsRes.value : { enrollments: [] };
          const subjectsData = subjectsRes.status === "fulfilled" ? subjectsRes.value : { subjects: [] };
          const assignmentsData = assignmentsRes.status === "fulfilled" ? assignmentsRes.value : { assignments: [], sections: [] };
          const specsData = specsRes.status === "fulfilled" ? specsRes.value : { specializations: [] };
          const scheduledData = scheduledRes.status === "fulfilled" ? scheduledRes.value : { classes: [] };

          setDataCache({
            rooms,
            faculty,
            programs,
            enrollments: enrollmentsData.enrollments ?? [],
            subjects: subjectsData.subjects ?? [],
            assignments: assignmentsData.assignments ?? [],
            sections: assignmentsData.sections ?? [],
            specializations: specsData.specializations ?? [],
            scheduledClasses: scheduledData.classes ?? [],
          });
          setIsLoading(false);
        })
        .catch((err) => {
          if (!isSubscribed) return;
          setError(err?.message || "Failed to load authoritative search indexes.");
          setIsLoading(false);
        });
    }

    return () => {
      isSubscribed = false;
    };
  }, [open, dataCache]);

  // Compute search results across all categories
  const groupedResults = useMemo(() => {
    const q = debouncedQuery.toLowerCase();
    if (!q) return [];

    const groups = [];

    // 1. Navigation / Application Pages
    const matchedPages = [];
    NAV_GROUPS.forEach((group) => {
      group.items.forEach((item) => {
        if (!item.to) return;
        const label = item.label;
        if (label.toLowerCase().includes(q) || group.label.toLowerCase().includes(q) || item.to.toLowerCase().includes(q)) {
          matchedPages.push({
            id: `page-${item.to}`,
            category: "navigation",
            title: label,
            subtitle: `${group.label} • Route: ${item.to}`,
            to: item.to,
          });
        }
      });
    });
    if (matchedPages.length > 0) {
      groups.push({ category: "navigation", items: matchedPages });
    }

    if (!dataCache) return groups;

    // 2. Faculty
    const matchedFaculty = [];
    (dataCache.faculty || []).forEach((f) => {
      const matchName = f.name?.toLowerCase().includes(q);
      const matchDept = f.department?.toLowerCase().includes(q);
      const matchType = f.faculty_type?.toLowerCase().includes(q);
      if (matchName || matchDept || matchType) {
        matchedFaculty.push({
          id: `faculty-${f.id}`,
          category: "faculty",
          title: f.name,
          subtitle: `${f.department || "No department"} • ${f.faculty_type || "regular"} • ${f.weekly_load ?? 0}/${f.weekly_max_hours ?? 24} hrs/wk`,
          to: `/timetable/faculty/${f.id}`,
          actionHint: "View Timetable",
        });
      }
    });
    if (matchedFaculty.length > 0) {
      groups.push({ category: "faculty", items: matchedFaculty.slice(0, 8) });
    }

    // 3. Subjects
    const matchedSubjects = [];
    (dataCache.subjects || []).forEach((s) => {
      const matchName = s.name?.toLowerCase().includes(q);
      const matchCode = s.code?.toLowerCase().includes(q);
      const matchProgram = s.program_name?.toLowerCase().includes(q);
      if (matchName || matchCode || matchProgram) {
        matchedSubjects.push({
          id: `subject-${s.id}`,
          category: "subjects",
          title: s.code ? `${s.code} — ${s.name}` : s.name,
          subtitle: `${s.program_name || "Program"} ${s.year_label || ""} • ${s.credits ?? 0} Credits • ${s.theory_hours_per_week ?? 0}h Theory, ${s.practical_hours_per_week ?? 0}h Lab`,
          to: "/subjects",
          actionHint: "Manage in Subjects",
        });
      }
    });
    if (matchedSubjects.length > 0) {
      groups.push({ category: "subjects", items: matchedSubjects.slice(0, 8) });
    }

    // 4. Programs & Enrollments
    const matchedPrograms = [];
    (dataCache.programs || []).forEach((p) => {
      if (p.name?.toLowerCase().includes(q) || p.department?.toLowerCase().includes(q)) {
        matchedPrograms.push({
          id: `prog-${p.id}`,
          category: "programs",
          title: p.name,
          subtitle: `Program • ${p.department || "General Department"}`,
          to: "/programs",
          actionHint: "View in Programs",
        });
      }
    });
    (dataCache.enrollments || []).forEach((e) => {
      if (
        e.program_name?.toLowerCase().includes(q) ||
        e.year_label?.toLowerCase().includes(q)
      ) {
        matchedPrograms.push({
          id: `enroll-${e.id}`,
          category: "programs",
          title: `${e.program_name} (${e.year_label})`,
          subtitle: `Enrollment • ${e.total_students} students`,
          to: `/enrollments/${e.id}/sections`,
          actionHint: "View Sections",
        });
      }
    });
    if (matchedPrograms.length > 0) {
      groups.push({ category: "programs", items: matchedPrograms.slice(0, 8) });
    }

    // 5. Sections
    const matchedSections = [];
    (dataCache.sections || []).forEach((sec) => {
      if (sec.name?.toLowerCase().includes(q)) {
        matchedSections.push({
          id: `section-${sec.id}`,
          category: "sections",
          title: sec.name,
          subtitle: `Section • ${sec.student_count ?? 0} students`,
          to: `/timetable/section/${sec.id}`,
          actionHint: "View Timetable",
        });
      }
    });
    if (matchedSections.length > 0) {
      groups.push({ category: "sections", items: matchedSections.slice(0, 8) });
    }

    // 6. Teaching Assignments
    const matchedAssignments = [];
    (dataCache.assignments || []).forEach((a) => {
      const matchSubj = a.subject_name?.toLowerCase().includes(q);
      const matchFac = a.faculty_name?.toLowerCase().includes(q);
      const matchGroup = a.group?.toLowerCase().includes(q);
      if (matchSubj || matchFac || matchGroup) {
        matchedAssignments.push({
          id: `assignment-${a.id}`,
          category: "assignments",
          title: `${a.subject_name} — ${a.group}`,
          subtitle: `Taught by ${a.faculty_name} • ${a.session_type} • ${a.periods_per_week} hrs/wk`,
          to: "/assignments",
          actionHint: "View Assignments",
        });
      }
    });
    if (matchedAssignments.length > 0) {
      groups.push({ category: "assignments", items: matchedAssignments.slice(0, 8) });
    }

    // 7. Rooms
    const matchedRooms = [];
    (dataCache.rooms || []).forEach((r) => {
      if (r.name?.toLowerCase().includes(q) || r.room_type?.toLowerCase().includes(q)) {
        matchedRooms.push({
          id: `room-${r.id}`,
          category: "rooms",
          title: `Room ${r.name}`,
          subtitle: `${r.room_type === "lab" ? "Laboratory" : "Theory Room"} • Capacity: ${r.capacity}${r.equipment_count ? ` • Equipment: ${r.equipment_count}` : ""}`,
          to: `/timetable/room/${r.id}`,
          actionHint: "View Timetable",
        });
      }
    });
    if (matchedRooms.length > 0) {
      groups.push({ category: "rooms", items: matchedRooms.slice(0, 8) });
    }

    // 8. Specializations
    const matchedSpecs = [];
    (dataCache.specializations || []).forEach((sp) => {
      if (sp.name?.toLowerCase().includes(q) || sp.session_type?.toLowerCase().includes(q)) {
        matchedSpecs.push({
          id: `spec-${sp.id}`,
          category: "specializations",
          title: sp.name,
          subtitle: `Specialization • ${sp.session_type || "theory"} • ${sp.periods_per_week || 0} periods/wk`,
          to: `/enrollments/${sp.enrollment_id}/specializations/${sp.id}`,
          actionHint: "View Details",
        });
      }
    });
    if (matchedSpecs.length > 0) {
      groups.push({ category: "specializations", items: matchedSpecs.slice(0, 8) });
    }

    // 9. Scheduled Classes
    const matchedClasses = [];
    (dataCache.scheduledClasses || []).forEach((sc) => {
      const matchDay = sc.day?.toLowerCase().includes(q);
      const matchSubj = sc.subject?.toLowerCase().includes(q);
      const matchFac = sc.faculty?.toLowerCase().includes(q);
      const matchRoom = sc.room?.toLowerCase().includes(q);
      const matchSec = (sc.section || sc.lab_group || sc.specialization)?.toLowerCase().includes(q);
      if (matchDay || matchSubj || matchFac || matchRoom || matchSec) {
        const groupLabel = sc.section || sc.lab_group || sc.specialization || "Class";
        matchedClasses.push({
          id: `sc-${sc.id}`,
          category: "scheduled",
          title: `${sc.subject} (${groupLabel})`,
          subtitle: `${sc.day} Period ${sc.start_period + 1} (${sc.length} period${sc.length > 1 ? "s" : ""}) • Room ${sc.room} • ${sc.faculty}${sc.is_locked ? " • [Locked]" : ""}`,
          to: sc.section_id ? `/timetable/section/${sc.section_id}` : `/timetable/faculty/${sc.faculty_id}`,
          actionHint: "View in Timetable",
        });
      }
    });
    if (matchedClasses.length > 0) {
      groups.push({ category: "scheduled", items: matchedClasses.slice(0, 8) });
    }

    return groups;
  }, [debouncedQuery, dataCache]);

  // Flattened list for keyboard navigation
  const flatResults = useMemo(() => {
    const list = [];
    groupedResults.forEach((group) => {
      group.items.forEach((item) => list.push(item));
    });
    return list;
  }, [groupedResults]);

  const safeSelectedIndex = flatResults.length > 0 ? Math.min(selectedIndex, flatResults.length - 1) : 0;

  const handleSelect = useCallback(
    (item) => {
      if (!item || !item.to) return;
      onOpenChange(false);
      navigate(item.to);
    },
    [navigate, onOpenChange]
  );

  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((prev) => (flatResults.length > 0 ? (prev + 1) % flatResults.length : 0));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((prev) => (flatResults.length > 0 ? (prev - 1 + flatResults.length) % flatResults.length : 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (flatResults[safeSelectedIndex]) {
          handleSelect(flatResults[safeSelectedIndex]);
        }
      } else if (e.key === "Escape") {
        e.preventDefault();
        onOpenChange(false);
      }
    },
    [flatResults, safeSelectedIndex, handleSelect, onOpenChange]
  );

  if (!open) return null;

  let currentIndexTracker = 0;
  const hasResultsPanel = Boolean(debouncedQuery || (isLoading && !dataCache) || error);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Universal Search"
      className="fixed inset-0 z-50 flex items-start justify-center p-4 sm:pt-24 bg-black/40 backdrop-blur-sm animate-in fade-in-0 duration-200"
      onClick={() => onOpenChange(false)}
      onKeyDown={handleKeyDown}
    >
      <div
        className="w-full max-w-2xl flex flex-col items-center gap-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Aceternity GooeyInput Component Integration (Light mode) */}
        <div className="w-full flex justify-center py-1">
          <GooeyInput
            id="universal-search-gooey-input"
            open={true}
            placeholder="Search faculty, subjects, rooms, classes, pages..."
            value={query}
            onValueChange={setQuery}
            onChange={(e) => setQuery(e.target.value)}
            onInput={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            collapsedWidth={140}
            expandedWidth={440}
            expandedOffset={60}
            gooeyBlur={4}
            className="w-full justify-center"
            classNames={{
              root: "w-full justify-center",
              trigger: "bg-white text-ink shadow-lg ring-1 ring-line/80 hover:bg-white focus-visible:ring-2 focus-visible:ring-brass",
              input: "text-ink placeholder:text-ink-soft/60 font-medium text-sm",
              bubbleSurface: "bg-white text-ink shadow-lg ring-1 ring-line/80",
            }}
          />
        </div>

        {/* Results Panel - only shown when query is present or loading/error */}
        {hasResultsPanel ? (
          <div
            ref={resultsListRef}
            className="w-full bg-white/95 border border-line rounded-2xl p-3 shadow-xl backdrop-blur-md max-h-[62vh] overflow-y-auto text-ink"
          >
            {isLoading && !dataCache ? (
              <div className="flex flex-col items-center justify-center py-10 text-ink-soft gap-2.5">
                <div className="size-5 border-2 border-line border-t-brass rounded-full animate-spin" />
                <p className="text-xs">Searching UniSchedule…</p>
              </div>
            ) : error ? (
              <div className="py-6 text-center text-signal text-xs">
                <p>{error}</p>
              </div>
            ) : flatResults.length === 0 ? (
              <div className="py-10 text-center text-ink-soft text-xs">
                <p className="font-medium text-ink text-sm">No results found for &ldquo;{debouncedQuery}&rdquo;</p>
                <p className="mt-1 text-ink-soft">Check your spelling or try searching for another faculty name, subject code, or room.</p>
              </div>
            ) : (
              <div className="space-y-3.5">
                {groupedResults.map((group) => {
                  const config = CATEGORY_CONFIG[group.category] || { label: group.category, icon: Sparkles };
                  const CategoryIcon = config.icon;

                  return (
                    <div key={group.category} className="space-y-1">
                      <div className="flex items-center gap-2 px-2.5 py-1 text-[11px] font-semibold text-ink-soft uppercase tracking-wider">
                        <CategoryIcon className="size-3.5 opacity-70" />
                        <span>{config.label}</span>
                        <span className="text-[10px] text-ink-soft/70 font-normal">({group.items.length})</span>
                      </div>

                      <div className="space-y-0.5">
                        {group.items.map((item) => {
                          const itemIndex = currentIndexTracker++;
                          const isSelected = itemIndex === safeSelectedIndex;

                          return (
                            <div
                              key={item.id}
                              role="button"
                              tabIndex={0}
                              onClick={() => handleSelect(item)}
                              onMouseEnter={() => setSelectedIndex(itemIndex)}
                              className={cn(
                                "group flex items-center justify-between px-3 py-2 rounded-xl cursor-pointer transition-all",
                                isSelected
                                  ? "bg-steel-tint text-steel shadow-xs border border-steel/20"
                                  : "text-ink hover:bg-paper"
                              )}
                            >
                              <div className="flex items-center gap-3 min-w-0 pr-2">
                                <div
                                  className={cn(
                                    "size-8 rounded-lg flex items-center justify-center shrink-0 text-xs font-semibold",
                                    isSelected ? "bg-steel text-white" : "bg-paper text-ink-soft"
                                  )}
                                >
                                  <CategoryIcon className="size-4" />
                                </div>

                                <div className="min-w-0">
                                  <p className={cn("text-sm font-semibold truncate", isSelected ? "text-steel font-bold" : "text-ink")}>
                                    {item.title}
                                  </p>
                                  <p className={cn("text-xs truncate", isSelected ? "text-steel/80" : "text-ink-soft")}>
                                    {item.subtitle}
                                  </p>
                                </div>
                              </div>

                              <div className="flex items-center gap-2 shrink-0">
                                {item.actionHint ? (
                                  <span
                                    className={cn(
                                      "hidden sm:inline-block text-[11px] px-2 py-0.5 rounded font-medium",
                                      isSelected
                                        ? "bg-steel/15 text-steel"
                                        : "bg-paper text-ink-soft group-hover:bg-line/60"
                                    )}
                                  >
                                    {item.actionHint}
                                  </span>
                                ) : null}
                                <ExternalLink className={cn("size-3.5 opacity-40 group-hover:opacity-100", isSelected && "opacity-80 text-steel")} />
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
