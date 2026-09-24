const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export function relativeTime(iso: string, now = new Date()): string {
  const then = new Date(iso);
  const delta = now.getTime() - then.getTime();
  if (Number.isNaN(then.getTime())) {
    return "";
  }
  if (delta < MINUTE) {
    return "Just now";
  }
  if (delta < HOUR) {
    const minutes = Math.floor(delta / MINUTE);
    return `${minutes} min ago`;
  }
  if (delta < DAY) {
    const hours = Math.floor(delta / HOUR);
    return hours === 1 ? "1 hour ago" : `${hours} hours ago`;
  }
  return dayLabel(then, now);
}

export function dayLabel(date: Date, now = new Date()): string {
  const startOf = (value: Date) => new Date(value.getFullYear(), value.getMonth(), value.getDate());
  const day = startOf(date).getTime();
  const today = startOf(now).getTime();
  if (day === today) {
    return "Today";
  }
  if (day === today - DAY) {
    return "Yesterday";
  }
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: date.getFullYear() === now.getFullYear() ? undefined : "numeric",
  }).format(date);
}

export function absoluteTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function conversationTitle(preview: string | null | undefined): string {
  const trimmed = preview?.trim() ?? "";
  if (trimmed === "") {
    return "New conversation";
  }
  return trimmed;
}
