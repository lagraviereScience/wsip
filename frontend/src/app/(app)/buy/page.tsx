import type { Metadata } from "next";
import { Suspense } from "react";

import { PAGE_SIZE, RecommendationGrid } from "@/components/games/recommendation-card";
import { PageSkeleton } from "@/components/layout/page-skeleton";
import { PreviewBanner } from "@/components/layout/preview-banner";
import { ListStatus } from "@/components/recommendations/list-status";
import { PendingRefresher } from "@/components/recommendations/pending-refresher";
import {
  UnownedFiltersForm,
  parseUnownedFilters,
} from "@/components/recommendations/unowned-filters";
import { PageHeader } from "@/components/ui/page-header";
import { getRecommendationList } from "@/lib/data";
import { getCurrentUser } from "@/lib/session";

export const metadata: Metadata = { title: "Games I Should Buy" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

async function Content({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const filters = parseUnownedFilters(params);
  const showAll = params.all === "1";
  const query = new URLSearchParams(
    Object.entries(params).flatMap(([k, v]) =>
      k === "all" || v === undefined ? [] : (Array.isArray(v) ? v : [v]).map((x) => [k, x]),
    ),
  );
  query.set("all", "1");
  const me = await getCurrentUser();
  const { source, data } = await getRecommendationList(
    me,
    "unowned",
    me ? filters : undefined,
    showAll ? undefined : PAGE_SIZE,
  );
  return (
    <>
      <PreviewBanner source={source} />
      <PageHeader
        eyebrow="Worth buying"
        title="Games I Should Buy"
        description="Games you don't own that match how you play. Price and reviews are shown next to the match, but they never change the ranking."
      >
        {me ? <UnownedFiltersForm filters={filters} /> : null}
      </PageHeader>
      {data.status === "pending" ? (
        <PendingRefresher />
      ) : (
        <>
          <ListStatus list={data} />
          <RecommendationGrid
            items={data.items}
            sample={source === "mock"}
            surface="buy"
            limit={showAll ? undefined : PAGE_SIZE}
            total={data.total}
            showAllHref={`?${query.toString()}`}
          />
          {source === "api" ? (
            <p className="mt-8 text-xs text-fg-subtle">
              Game data and prices provided by Steam (US store). Prices can change at any time.
            </p>
          ) : null}
        </>
      )}
    </>
  );
}

export default function BuyPage({ searchParams }: { searchParams: SearchParams }) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Content searchParams={searchParams} />
    </Suspense>
  );
}
