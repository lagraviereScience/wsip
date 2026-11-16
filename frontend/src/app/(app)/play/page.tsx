import type { Metadata } from "next";
import { Suspense } from "react";

import { PAGE_SIZE, RecommendationGrid } from "@/components/games/recommendation-card";
import { PageSkeleton } from "@/components/layout/page-skeleton";
import { PreviewBanner } from "@/components/layout/preview-banner";
import { ListStatus } from "@/components/recommendations/list-status";
import { PendingRefresher } from "@/components/recommendations/pending-refresher";
import { PageHeader } from "@/components/ui/page-header";
import { getRecommendationList } from "@/lib/data";
import { getCurrentUser } from "@/lib/session";

export const metadata: Metadata = { title: "Games I Should Play" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

async function Content({ searchParams }: { searchParams: SearchParams }) {
  const showAll = (await searchParams).all === "1";
  const me = await getCurrentUser();
  const { source, data } = await getRecommendationList(me, "owned", undefined, showAll ? undefined : PAGE_SIZE);
  return (
    <>
      <PreviewBanner source={source} />
      <PageHeader
        eyebrow="From your library"
        title="Games I Should Play"
        description="Games you already own, ranked by how well they fit your profile (85%) and how much of a backlog opportunity they are (15%). Games you're playing right now or have already sunk 100+ hours into are left out."
      />
      {data.status === "pending" ? (
        <PendingRefresher />
      ) : (
        <>
          <ListStatus list={data} />
          <RecommendationGrid
            items={data.items}
            sample={source === "mock"}
            surface="play"
            limit={showAll ? undefined : PAGE_SIZE}
            total={data.total}
            showAllHref="?all=1"
          />
        </>
      )}
    </>
  );
}

export default function PlayPage({ searchParams }: { searchParams: SearchParams }) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Content searchParams={searchParams} />
    </Suspense>
  );
}
