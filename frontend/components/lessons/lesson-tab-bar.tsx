"use client";

import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { LessonTab, TabId, TabTone } from "@/lib/lesson-tabs";

const BADGE: Record<TabTone, "marigold" | "success" | "destructive-soft"> = {
  marigold: "marigold",
  success: "success",
  destructive: "destructive-soft",
};

type Props = {
  tabs: LessonTab[];
  active: TabId;
  onChange: (tab: TabId) => void;
  /** What each tab shows. */
  panels: Record<TabId, React.ReactNode>;
};

/** The tabs under the journey stepper. Which one is open lives in the address (`?tab=`), so a tab can be linked to. */
export function LessonTabBar({ tabs, active, onChange, panels }: Props) {
  return (
    <Tabs value={active} onValueChange={(value) => onChange(value as TabId)} className="gap-5">
      <TabsList variant="line" className="group-data-horizontal/tabs:h-auto h-auto w-full flex-wrap justify-start gap-x-1 gap-y-0 border-b border-border p-0">
        {tabs.map((tab) => (
          <TabsTrigger key={tab.id} value={tab.id} className="h-auto flex-none gap-2 px-3 py-2.5 text-sm font-extrabold after:bottom-[-1px] after:bg-primary">
            {tab.label}
            {tab.badge && <Badge variant={BADGE[tab.badge.tone]}>{tab.badge.text}</Badge>}
          </TabsTrigger>
        ))}
      </TabsList>
      {tabs.map((tab) => (
        <TabsContent key={tab.id} value={tab.id} className="flex flex-col gap-6 text-base">
          {tab.id === active ? panels[tab.id] : null}
        </TabsContent>
      ))}
    </Tabs>
  );
}
