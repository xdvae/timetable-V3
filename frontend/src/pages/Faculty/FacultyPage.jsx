import { PagePlaceholder } from "@/components/layout/placeholder.jsx";

export function FacultyPage() {
  return <PagePlaceholder title="Faculty" subtitle="Roster, weekly loads, and availability." route="/faculty" />;
}

export function FacultyAvailabilityPage() {
  return (
    <PagePlaceholder
      title="Faculty Availability"
      subtitle="Unavailable day × period slots per faculty member."
      route="/faculty/:fid/availability"
    />
  );
}
