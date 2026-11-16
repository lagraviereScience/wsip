import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { GameSearch } from "@/components/library/game-search";
import { PageSkeleton } from "@/components/layout/page-skeleton";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { getCurrentUser } from "@/lib/session";

export const metadata: Metadata = { title: "Add games" };

async function Add() {
  const me = await getCurrentUser();
  if (!me) redirect("/library");
  return (
    <Card>
      <CardContent className="p-6">
        <GameSearch />
      </CardContent>
    </Card>
  );
}

export default function AddGamesPage() {
  return (
    <>
      <PageHeader
        eyebrow="My Game Library"
        title="Add games"
        description="Find games on Steam, tick the ones you own and rate the ones you've played."
      />
      <Suspense fallback={<PageSkeleton />}>
        <Add />
      </Suspense>
    </>
  );
}
