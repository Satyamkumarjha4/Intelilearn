"use client";

import {
  closestCenter,
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ArrowUpIcon, GripVerticalIcon, XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ModelCatalog } from "@/lib/model-catalog";
import { RoutingDraft } from "@/lib/routing-draft";
import { RoutingView } from "@/lib/routing-view";
import type { ConsoleModel, NodeRouting, RoutingBinding } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = { node: NodeRouting; models: ReadonlyMap<number, ConsoleModel>; onChange: (node: NodeRouting) => void };

const idOf = (binding: RoutingBinding, index: number) => (binding.model === null ? `missing-${index}-${binding.model_label}` : `model-${binding.model}`);

function Item({ id, index, binding, model, node, onChange }: { id: string; index: number; binding: RoutingBinding; model?: ConsoleModel; node: NodeRouting; onChange: Props["onChange"] }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
    id,
    // The buttons reorder without a drag, and an error note can appear above the list at any time: animating those layout
    // shifts from a stale measurement leaves the items offset. Only the drag itself moves them.
    animateLayoutChanges: () => false,
  });
  const [provider, ...rest] = binding.model_label.split("/");
  const name = rest.length ? rest.join("/") : binding.model_label;
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn("grid grid-cols-[auto_26px_minmax(0,1fr)_auto] items-center gap-2.5 rounded-xl border-[1.5px] bg-card p-2.5", isDragging && "relative z-10 opacity-70 shadow-card", !binding.enabled && "opacity-70")}
    >
      <button
        type="button"
        ref={setActivatorNodeRef}
        {...attributes}
        {...listeners}
        aria-label={`Move ${name}. Press space, then the arrow keys, then space again.`}
        className="grid size-7 cursor-grab touch-none place-items-center rounded-md text-muted-foreground outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 active:cursor-grabbing"
      >
        <GripVerticalIcon className="size-4" aria-hidden="true" />
      </button>
      <span className={cn("grid size-[26px] place-items-center rounded-lg bg-muted text-xs font-extrabold", index === 0 && "bg-primary text-primary-foreground")} aria-hidden="true">
        {index + 1}
      </span>
      <div className="min-w-0">
        <b className="block truncate font-mono text-[13px] font-semibold" title={binding.model_label}>{name}</b>
        <small className="block text-xs text-muted-foreground">
          {RoutingView.caption(index)} · {ModelCatalog.providerName(provider)} · {RoutingView.price(model)}
          {binding.enabled ? "" : " · switched off"}
        </small>
        {binding.problems.map((problem) => (
          <small key={problem} className="block text-xs font-bold text-destructive-text">
            {problem}
          </small>
        ))}
      </div>
      <span className="flex gap-1.5">
        <Button variant="outline" size="icon-sm" disabled={index === 0} onClick={() => onChange(RoutingDraft.moveUp(node, index))} aria-label={`Move ${name} up`}>
          <ArrowUpIcon />
        </Button>
        <Button variant="outline" size="icon-sm" disabled={!RoutingDraft.canRemove(node)} onClick={() => onChange(RoutingDraft.remove(node, index))} aria-label={`Remove ${name}`}>
          <XIcon />
        </Button>
      </span>
    </li>
  );
}

/** The models of a step in priority order. Drag the handle (or focus it and use the keyboard), or use the buttons. */
export function BindingList({ node, models, onChange }: Props) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));
  const ids = node.bindings.map(idOf);
  const label = (id: string | number) => {
    const index = ids.indexOf(String(id));
    return node.bindings[index]?.model_label ?? "model";
  };

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from >= 0 && to >= 0) onChange(RoutingDraft.reorder(node, from, to));
  };

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={onDragEnd}
      accessibility={{
        announcements: {
          onDragStart: ({ active }) => `Picked up ${label(active.id)}.`,
          onDragOver: ({ active, over }) => (over ? `${label(active.id)} is over place ${ids.indexOf(String(over.id)) + 1}.` : undefined),
          onDragEnd: ({ active, over }) => (over ? `${label(active.id)} was put in place ${ids.indexOf(String(over.id)) + 1}.` : `${label(active.id)} was put back.`),
          onDragCancel: ({ active }) => `Moving ${label(active.id)} was cancelled.`,
        },
      }}
    >
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        <ol aria-label="Models in priority order" className="grid gap-2">
          {node.bindings.map((binding, index) => (
            <Item key={ids[index]} id={ids[index]} index={index} binding={binding} model={binding.model === null ? undefined : models.get(binding.model)} node={node} onChange={onChange} />
          ))}
        </ol>
      </SortableContext>
    </DndContext>
  );
}

