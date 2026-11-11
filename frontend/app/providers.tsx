"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Shell } from "@/components/Shell";

export function Providers({ children }: { children: React.ReactNode }) {
  const [qc] = useState(() => new QueryClient({ defaultOptions: { queries: { staleTime: 1000, refetchOnWindowFocus: false, retry: 1 } } }));
  return (
    <QueryClientProvider client={qc}>
      <Shell>{children}</Shell>
    </QueryClientProvider>
  );
}
