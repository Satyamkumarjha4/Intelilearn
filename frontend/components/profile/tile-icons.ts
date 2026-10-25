import {
  BriefcaseIcon,
  CircleHelpIcon,
  ClipboardCheckIcon,
  CompassIcon,
  EyeIcon,
  GraduationCapIcon,
  HandIcon,
  LanguagesIcon,
  LayersIcon,
  LibraryIcon,
  LightbulbIcon,
  MessagesSquareIcon,
  BookOpenIcon,
  SchoolIcon,
  ZapIcon,
  type LucideIcon,
} from "lucide-react";

/** The icon of each tile, by the value the API accepts. A value we have no icon for (a new one) gets a neutral one. */
const ICONS: Record<string, LucideIcon> = {
  school: SchoolIcon,
  undergraduate: GraduationCapIcon,
  postgraduate: LibraryIcon,
  professional: BriefcaseIcon,
  self_learner: CompassIcon,
  visual: EyeIcon,
  reading: BookOpenIcon,
  hands_on: HandIcon,
  mixed: LayersIcon,
  exam_prep: ClipboardCheckIcon,
  deep_understanding: LightbulbIcon,
  quick_overview: ZapIcon,
  interview_prep: MessagesSquareIcon,
};

export const tileIcon = (value: string): LucideIcon => ICONS[value] ?? CircleHelpIcon;
export const LanguageIcon = LanguagesIcon;
