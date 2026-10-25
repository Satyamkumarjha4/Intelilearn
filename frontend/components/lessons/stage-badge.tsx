import { Badge } from "@/components/ui/badge";
import type { Stage } from "@/lib/types";

const LABELS: Record<Stage, { text: string; variant: "default" | "secondary" | "outline" | "destructive" | "success" }> = {
  preparing_diagnostic: { text: "Preparing quiz", variant: "secondary" },
  awaiting_diagnostic: { text: "Quiz ready", variant: "default" },
  awaiting_prerequisite: { text: "Foundations quiz", variant: "default" },
  awaiting_choice: { text: "Choose a sheet", variant: "default" },
  generating_material: { text: "Writing sheet", variant: "secondary" },
  generating_lesson: { text: "Building lesson", variant: "secondary" },
  ready: { text: "Ready", variant: "success" },
  failed: { text: "Failed", variant: "destructive" },
};

export function StageBadge({ stage }: { stage: Stage }) {
  const { text, variant } = LABELS[stage];
  return <Badge variant={variant}>{text}</Badge>;
}
