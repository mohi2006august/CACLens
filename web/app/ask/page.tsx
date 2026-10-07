import type { Metadata } from "next";
import { Suspense } from "react";

import { Controls } from "@/components/Controls";
import { PageHead } from "@/components/ui";
import { AskClient } from "./AskClient";

export const metadata: Metadata = { title: "Ask" };

export default function AskPage() {
  return (
    <>
      <PageHead
        title="Ask"
        subtitle="Plain-English questions, answered only through the semantic layer. Every answer shows the exact queries it ran."
      />
      <Suspense fallback={null}>
        <Controls showRange={false} />
        <AskClient />
      </Suspense>
    </>
  );
}
