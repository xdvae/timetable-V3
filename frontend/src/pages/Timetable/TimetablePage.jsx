import { PagePlaceholder } from "@/components/layout/placeholder.jsx";

export function TimetablePage() {
  return (
    <PagePlaceholder
      title="Timetable"
      subtitle="Generate the schedule, then look it up by section, faculty, or room."
      route="/timetable"
    />
  );
}

export function TimetableViewPage() {
  return (
    <PagePlaceholder
      title="Timetable View"
      subtitle="Day × period grid for one section, faculty member, or room."
      route="/timetable/:view/:id"
    />
  );
}
