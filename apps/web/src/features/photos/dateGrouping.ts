import type { PhotoTimelineGroup } from "../../api/photos";
import { appLocale } from "../../lib/format";

export type TimelineMonthGroup = {
  days: PhotoTimelineGroup[];
  monthLabel: string;
};

const dateFormatter = new Intl.DateTimeFormat(appLocale(), {
  day: "numeric",
  month: "long",
  timeZone: "UTC",
  weekday: "long",
  year: "numeric",
});

const monthFormatter = new Intl.DateTimeFormat(appLocale(), {
  month: "long",
  timeZone: "UTC",
  year: "numeric",
});

export function groupTimelineByMonth(groups: PhotoTimelineGroup[]): TimelineMonthGroup[] {
  const months = new Map<string, TimelineMonthGroup>();

  for (const group of groups) {
    const date = parseTimelineDate(group.date);
    const monthKey = `${date.getUTCFullYear()}-${date.getUTCMonth()}`;
    const monthLabel = monthFormatter.format(date);
    const current = months.get(monthKey) ?? { days: [], monthLabel };
    current.days.push(group);
    months.set(monthKey, current);
  }

  return Array.from(months.values());
}

export function formatTimelineDate(value: string): string {
  return dateFormatter.format(parseTimelineDate(value));
}

function parseTimelineDate(value: string): Date {
  const date = new Date(`${value.slice(0, 10)}T00:00:00.000Z`);

  if (Number.isNaN(date.getTime())) {
    return new Date(0);
  }

  return date;
}
