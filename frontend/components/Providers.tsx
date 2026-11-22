"use client";

import { createTheme, MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { createContext, useContext } from "react";
import { useApi } from "@/lib/api";
import { catMap } from "@/lib/format";
import type { Category } from "@/lib/types";
import { Shell } from "./Shell";

const theme = createTheme({
  primaryColor: "indigo",
  defaultRadius: "md",
  fontFamily: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif",
});

interface CategoriesCtx {
  list: Category[];
  byKey: Record<string, Category>;
  reload: () => Promise<void>;
}

const Ctx = createContext<CategoriesCtx>({ list: [], byKey: {}, reload: async () => {} });

export function useCategories() {
  return useContext(Ctx);
}

function CategoriesProvider({ children }: { children: React.ReactNode }) {
  const { data, reload } = useApi<Category[]>("/api/categories");
  const list = (data ?? []).filter((c) => c.active);
  return <Ctx.Provider value={{ list, byKey: catMap(data), reload }}>{children}</Ctx.Provider>;
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <MantineProvider theme={theme} defaultColorScheme="auto">
      <Notifications position="bottom-right" />
      <CategoriesProvider>
        <Shell>{children}</Shell>
      </CategoriesProvider>
    </MantineProvider>
  );
}
