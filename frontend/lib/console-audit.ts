import type { AuditEntry } from "@/lib/types";

export type Segment = { text: string; code?: boolean };
export type AuditArea = "routing" | "models" | "settings" | "runs";

const NONE = "–";
const AREA_OF: Record<string, AuditArea> = { node: "routing", model: "models", provider: "models", flow_settings: "settings", run: "runs" };

const FIELD_NAMES: Record<string, string> = {
  rpm_limit: "rate limit",
  timeout_s: "timeout",
  base_url: "base URL",
  bindings: "models",
  params_override: "parameters",
  default_params: "default parameters",
  input_cost_per_mtok: "input price",
  output_cost_per_mtok: "output price",
};

type Snapshot = Record<string, unknown>;
const snap = (value: unknown): Snapshot => (value && typeof value === "object" && !Array.isArray(value) ? (value as Snapshot) : {});
const code = (text: string): Segment => ({ text, code: true });
const plain = (text: string): Segment => ({ text });

/** The areas of the change log, as the filter offers them. A change is in the area of the thing it changed. */
export class AuditAreas {
  static readonly OPTIONS: readonly { value: AuditArea; label: string }[] = [
    { value: "routing", label: "Routing" },
    { value: "models", label: "Models" },
    { value: "settings", label: "Settings" },
    { value: "runs", label: "Runs" },
  ];

  static of(entry: Pick<AuditEntry, "target_type">): AuditArea | null {
    return AREA_OF[entry.target_type] ?? null;
  }

  /** The entries of one area, in their order; every entry for "". */
  static filter<T extends Pick<AuditEntry, "target_type">>(entries: readonly T[], area: AuditArea | ""): T[] {
    return area ? entries.filter((entry) => AuditAreas.of(entry) === area) : [...entries];
  }

  /** What `?area=` may hold: a known area, else nothing. */
  static parse(value: string | null): AuditArea | "" {
    return AuditAreas.OPTIONS.find((option) => option.value === value)?.value ?? "";
  }

  /** `""` for all areas, else `?area=models`. */
  static query(area: AuditArea | ""): string {
    return area ? `?area=${area}` : "";
  }
}

/** A change as a sentence, with the things it touched marked as code. */
export class AuditText {
  /** `modelNames` (id to name) names a model whose entry only has its id (a test of a model keeps no snapshot of it). */
  static sentence(entry: AuditEntry, modelNames: ReadonlyMap<string, string> = new Map()): Segment[] {
    const { action, target_id: id } = entry;
    const before = snap(entry.before);
    const after = snap(entry.after);
    const fields = entry.changed_fields;
    const modelName = () => String(after.name ?? before.name ?? modelNames.get(id) ?? id);

    switch (action) {
      case "model.create":
        return [plain("Added model "), code(modelName())];
      case "model.delete":
        return [plain("Deleted model "), code(modelName())];
      case "model.probe":
        return [plain("Tested model "), code(modelName()), plain(after.ok ? ": it worked" : ": it failed")];
      case "model.update":
        return AuditText.update("model", modelName(), fields, after);
      case "provider.update":
        return AuditText.update("provider", id, fields, after);
      case "node.update":
        return AuditText.routing(id, fields, before, after);
      case "flow_settings.update":
        return [plain(`Changed lesson settings: ${AuditText.list(fields.map(AuditText.fieldName))}`)];
      case "run.retry":
        return [plain("Retried run "), code(id.slice(0, 8))];
      case "run.cancel":
        return [plain("Stopped run "), code(id.slice(0, 8))];
      default:
        return [plain("Ran "), code(action), plain(" on "), code(id)];
    }
  }

  /** "a", "a and b", "a, b and c", "a, b, c and 2 more". */
  static list(items: readonly string[]): string {
    if (items.length <= 3) return items.length > 1 ? `${items.slice(0, -1).join(", ")} and ${items.at(-1)}` : (items[0] ?? "");
    return `${items.slice(0, 3).join(", ")} and ${items.length - 3} more`;
  }

  /** A field as words: "max_attempts" as "max attempts", and the ones that are jargon by a plain name. */
  static fieldName(field: string): string {
    return FIELD_NAMES[field] ?? field.replaceAll("_", " ");
  }

  static actor(entry: Pick<AuditEntry, "actor" | "actor_email">): { initial: string; name: string; title: string } {
    const who = entry.actor?.name?.trim() || entry.actor_email;
    return { initial: who ? who.charAt(0).toUpperCase() : "?", name: who || "Someone", title: entry.actor_email };
  }

  private static update(kind: "model" | "provider", name: string, fields: readonly string[], after: Snapshot): Segment[] {
    if (fields.length === 1 && fields[0] === "enabled") return [plain(`Turned ${kind} `), code(name), plain(after.enabled ? " on" : " off")];
    return [plain(`Changed ${AuditText.list(fields.map(AuditText.fieldName))} of ${kind} `), code(name)];
  }

  /** A step's change: its settings, then what happened to its chain of models (added, removed, or only reordered). */
  private static routing(node: string, fields: readonly string[], before: Snapshot, after: Snapshot): Segment[] {
    const sentences: Segment[][] = [];
    const settings = fields.filter((field) => field !== "bindings");
    if (settings.length) sentences.push([plain(`Changed ${AuditText.list(settings.map(AuditText.fieldName))} of `), code(node)]);

    if (fields.includes("bindings")) {
      const was = AuditDiff.chain(before.bindings);
      const now = AuditDiff.chain(after.bindings);
      const added = now.filter((label) => !was.includes(label));
      const removed = was.filter((label) => !now.includes(label));
      added.forEach((label) => sentences.push([plain("Added "), code(label), plain(" to "), code(node)]));
      removed.forEach((label) => sentences.push([plain("Removed "), code(label), plain(" from "), code(node)]));
      if (!added.length && !removed.length) sentences.push([plain("Changed the order of the models of "), code(node)]);
    }
    return sentences.length ? sentences.flatMap((sentence, index) => (index ? [plain(". "), ...sentence] : sentence)) : [plain("Changed "), code(node)];
  }
}

export type DiffRow = { field: string; before: string; after: string };

/** What a change did to each field it touched, in words: before and after side by side. */
export class AuditDiff {
  static rows(entry: Pick<AuditEntry, "before" | "after" | "changed_fields">): DiffRow[] {
    const before = snap(entry.before);
    const after = snap(entry.after);
    return entry.changed_fields.map((field) => ({
      field: AuditText.fieldName(field),
      before: AuditDiff.value(field, before[field]),
      after: AuditDiff.value(field, after[field]),
    }));
  }

  /** One value as text: on/off, a dash for nothing, a model chain as "a → b", anything nested as compact JSON. */
  static value(field: string, value: unknown): string {
    if (value === null || value === undefined || value === "") return NONE;
    if (typeof value === "boolean") return value ? "on" : "off";
    if (typeof value === "string" || typeof value === "number") return String(value);
    if (field === "bindings") {
      const labels = AuditDiff.chain(value);
      return labels.length ? labels.join(" → ") : "none";
    }
    return JSON.stringify(value);
  }

  /** The model labels of a step's chain, in priority order. */
  static chain(bindings: unknown): string[] {
    if (!Array.isArray(bindings)) return [];
    return bindings.map((binding) => String(snap(binding).model_label ?? "")).filter(Boolean);
  }
}
