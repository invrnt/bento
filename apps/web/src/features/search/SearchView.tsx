import { useMemo, useState } from "react";
import { SearchX } from "lucide-react";

import { PageHeader } from "../../components/PageHeader";
import { ErrorState, EmptyState, LoadingState } from "../../components/States";
import type { SearchApi } from "../../api/search";
import { t } from "../../i18n/dictionary";
import { cx } from "../../lib/cx";
import { SearchFiltersBar } from "./SearchFiltersBar";
import { SearchResultsList } from "./SearchResultsList";
import type { SearchFilters, SearchScope } from "./searchFilters";
import { parseSearchFilters, toUrlSearch } from "./searchFilters";
import { useSearchResults } from "./useSearchResults";

export type SearchViewProps = {
  client?: SearchApi;
  scope?: SearchScope;
};

export function SearchView({ client, scope = "global" }: SearchViewProps) {
  const initialFilters = useMemo(() => parseSearchFilters(window.location.search, scope), [scope]);
  const [filters, setFilters] = useState<SearchFilters>(initialFilters);
  const results = useSearchResults(filters, client);
  const title = scope === "documents" ? t("documents.title") : t("search.title");
  const body = scope === "documents" ? t("documents.subtitle") : t("search.subtitle");
  const items = results.data?.items ?? [];
  const refreshing = results.isLoading && results.data !== null;

  function updateFilters(nextFilters: SearchFilters): void {
    setFilters(nextFilters);
    const nextSearch = toUrlSearch(nextFilters);
    const nextUrl = `${window.location.pathname}${nextSearch ? `?${nextSearch}` : ""}`;
    window.history.pushState({}, "", nextUrl);
  }

  return (
    <div className="grid w-full gap-8">
      <PageHeader description={body} title={title}>
        <SearchFiltersBar filters={filters} onChange={updateFilters} scope={scope} />
      </PageHeader>

      {results.isLoading && results.data === null ? <LoadingState label={t("search.loading")} /> : null}
      {results.error ? <ErrorState body={t("search.error")} onRetry={results.refetch} /> : null}
      {!results.isLoading && !results.error && results.data && items.length === 0 ? (
        <EmptyState body={t("search.empty.body")} icon={<SearchX />} title={t("search.empty.title")} />
      ) : null}
      {!results.error && items.length > 0 ? (
        <div aria-busy={refreshing || undefined} className={cx("transition-opacity duration-150", refreshing && "opacity-60")}>
          <SearchResultsList items={items} />
        </div>
      ) : null}
    </div>
  );
}
