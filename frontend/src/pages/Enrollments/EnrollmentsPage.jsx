import { PagePlaceholder } from "@/components/layout/placeholder.jsx";

export function EnrollmentsPage() {
  return (
    <PagePlaceholder
      title="Enrollments & Sections"
      subtitle="Cohorts with auto-generated sections and lab groups."
      route="/enrollments"
    />
  );
}

export function SectionsPage() {
  return (
    <PagePlaceholder
      title="Sections"
      subtitle="Auto-generated sections and lab groups for one enrollment."
      route="/enrollments/:eid/sections"
    />
  );
}
