import { Folder, Search, X } from "lucide-react";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Input } from "../../components/Input";
import { Select } from "../../components/Select";
import { t } from "../../i18n/dictionary";
import type { SearchResultType } from "../../api/search";
import type { SearchFilters, SearchScope } from "./searchFilters";
import { documentTypeOptions, searchTypeOptions } from "./searchFilters";

export type SearchFiltersBarProps = {
  filters: SearchFilters;
  onChange: (filters: SearchFilters) => void;
  scope: SearchScope;
};

export function SearchFiltersBar({ filters, onChange, scope }: SearchFiltersBarProps) {
  const typeOptions =
    scope === "documents"
      ? documentTypeOptions.map((option) => ({ label: t(option.labelKey), value: option.value }))
      : searchTypeOptions.map((option) => ({ label: t(option.labelKey), value: option.value }));
  const activeCount = countActiveFilters(filters, scope);

  function updateFilter(key: keyof SearchFilters, value: string): void {
    onChange({
      ...filters,
      [key]: key === "type" ? normalizeType(value, scope) : value,
    });
  }

  function clearFilters(): void {
    onChange({ ...filters, dateFrom: "", dateTo: "", folderId: "", type: scope === "documents" ? "document" : "" });
  }

  return (
    <section
      aria-label={t(scope === "documents" ? "documents.filters.label" : "search.filters.label")}
      className="grid gap-3"
    >
      <Input
        className="h-11 text-md"
        hideLabel
        label={t("search.filter.query")}
        leadingIcon={<Search />}
        onChange={(event) => updateFilter("q", event.currentTarget.value)}
        placeholder={t("search.filter.queryPlaceholder")}
        type="search"
        value={filters.q}
      />
      <div className="flex flex-wrap items-end gap-3">
        <Select
          label={t("search.filter.type")}
          onChange={(event) => updateFilter("type", event.currentTarget.value)}
          options={typeOptions}
          value={filters.type}
          wrapperClassName="w-full sm:w-44"
        />
        <Input
          className="font-mono text-sm"
          label={t("search.filter.folder")}
          leadingIcon={<Folder />}
          onChange={(event) => updateFilter("folderId", event.currentTarget.value)}
          placeholder={t("search.filter.folderPlaceholder")}
          value={filters.folderId}
          wrapperClassName="w-full sm:w-48"
        />
        <Input
          label={t("search.filter.dateFrom")}
          max={filters.dateTo || undefined}
          onChange={(event) => updateFilter("dateFrom", event.currentTarget.value)}
          type="date"
          value={filters.dateFrom}
          wrapperClassName="w-[calc(50%-0.375rem)] sm:w-40"
        />
        <Input
          label={t("search.filter.dateTo")}
          min={filters.dateFrom || undefined}
          onChange={(event) => updateFilter("dateTo", event.currentTarget.value)}
          type="date"
          value={filters.dateTo}
          wrapperClassName="w-[calc(50%-0.375rem)] sm:w-40"
        />
        {activeCount > 0 ? (
          <div className="flex h-9 items-center gap-2 sm:ml-auto">
            <Badge tone="accent">
              {activeCount === 1 ? t("search.filters.activeOne") : t("search.filters.activeMany").replace("{count}", String(activeCount))}
            </Badge>
            <Button leadingIcon={<X />} onClick={clearFilters} size="sm" variant="ghost">
              {t("search.filters.clear")}
            </Button>
          </div>
        ) : null}
      </div>
    </section>
  );
}

export function countActiveFilters(filters: SearchFilters, scope: SearchScope): number {
  return [
    scope === "global" ? filters.type : "",
    filters.folderId.trim(),
    filters.dateFrom,
    filters.dateTo,
  ].filter(Boolean).length;
}

function normalizeType(value: string, scope: SearchScope): SearchResultType | "" {
  if (scope === "documents") {
    return value === "pdf_page" ? "pdf_page" : "document";
  }

  return value as SearchResultType | "";
}
