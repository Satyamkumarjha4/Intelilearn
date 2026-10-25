import { cn } from "@/lib/utils";

type RowProps = {
  /** The id of the control, so the label is attached to it. */
  htmlFor?: string;
  label: React.ReactNode;
  help?: React.ReactNode;
  /** A message for this field; the control should point at it with `aria-describedby={errorId(htmlFor)}`. */
  error?: string;
  children: React.ReactNode;
  className?: string;
  /** Use when the control is not a form input (a switch has its own label id). */
  labelId?: string;
};

export const errorId = (id: string) => `${id}-error`;

/** A setting: its name and help on the left, the control on the right, and what is wrong with it underneath. */
export function FieldRow({ htmlFor, label, help, error, children, className, labelId }: RowProps) {
  return (
    <div className={cn("grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 border-b border-border/60 py-2.5 last:border-b-0 max-[560px]:grid-cols-1", className)}>
      <div className="min-w-0">
        {htmlFor ? (
          <label htmlFor={htmlFor} className="font-bold">
            {label}
          </label>
        ) : (
          <span id={labelId} className="font-bold">
            {label}
          </span>
        )}
        {help ? <small className="block text-xs font-semibold text-muted-foreground">{help}</small> : null}
      </div>
      <div className="flex items-center justify-end gap-1.5 max-[560px]:justify-start">{children}</div>
      {error && htmlFor ? (
        <p id={errorId(htmlFor)} className="col-span-full text-xs font-bold text-destructive-text">
          {error}
        </p>
      ) : null}
    </div>
  );
}

type NumberBoxProps = {
  id: string;
  value: string;
  onChange: (value: string) => void;
  invalid?: boolean;
  ariaLabel?: string;
  width?: string;
  disabled?: boolean;
  /** The id of the element that says what is wrong, when it is not `errorId(id)` (two boxes sharing one message). */
  errorFor?: string;
};

/** A box for a whole number. It holds text, because what is typed on the way to a number is not one yet. */
export function NumberBox({ id, value, onChange, invalid = false, ariaLabel, width = "w-[90px]", disabled, errorFor }: NumberBoxProps) {
  return (
    <input
      id={id}
      type="text"
      inputMode="numeric"
      autoComplete="off"
      value={value}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-invalid={invalid || undefined}
      aria-describedby={invalid ? (errorFor ?? errorId(id)) : undefined}
      onChange={(event) => onChange(event.target.value)}
      className={cn(
        "h-8 rounded-[9px] border-[1.5px] bg-card px-2.5 text-right font-mono text-[13px] outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50 aria-invalid:border-destructive",
        width,
      )}
    />
  );
}

type StackedProps = {
  id: string;
  label: React.ReactNode;
  help?: React.ReactNode;
  error?: string;
  children: React.ReactNode;
  className?: string;
};

/** A field for a form in a dialog: label above, control, then what is wrong (or a hint). */
export function StackedField({ id, label, help, error, children, className }: StackedProps) {
  return (
    <div className={cn("grid content-start gap-1", className)}>
      <label htmlFor={id} className="text-[13px] font-bold">
        {label}
      </label>
      {children}
      {error ? (
        <p id={errorId(id)} className="text-xs font-bold text-destructive-text">
          {error}
        </p>
      ) : help ? (
        <p className="text-xs font-semibold text-muted-foreground">{help}</p>
      ) : null}
    </div>
  );
}

const BOX =
  "h-8 w-full min-w-0 rounded-[9px] border-[1.5px] bg-card px-2.5 text-[13px] outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50 aria-invalid:border-destructive";

type TextBoxProps = {
  id: string;
  value: string;
  onChange: (value: string) => void;
  error?: string;
  mono?: boolean;
  placeholder?: string;
  inputMode?: "numeric" | "decimal" | "url" | "text";
  disabled?: boolean;
};

export function TextBox({ id, value, onChange, error, mono = false, placeholder, inputMode, disabled }: TextBoxProps) {
  return (
    <input
      id={id}
      type="text"
      value={value}
      disabled={disabled}
      inputMode={inputMode}
      placeholder={placeholder}
      autoComplete="off"
      spellCheck={false}
      aria-invalid={error ? true : undefined}
      aria-describedby={error ? errorId(id) : undefined}
      onChange={(event) => onChange(event.target.value)}
      className={cn(BOX, mono && "font-mono")}
    />
  );
}

type SelectBoxProps = {
  id: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly { value: string; label: string }[];
  error?: string;
  disabled?: boolean;
  className?: string;
  ariaLabel?: string;
};

/** The browser's own select, in the console's box style: it is keyboard and screen-reader complete as it is. */
export function SelectBox({ id, value, onChange, options, error, disabled, className, ariaLabel }: SelectBoxProps) {
  return (
    <select
      id={id}
      value={value}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-invalid={error ? true : undefined}
      aria-describedby={error ? errorId(id) : undefined}
      onChange={(event) => onChange(event.target.value)}
      className={cn(BOX, "font-semibold", className)}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

/** A tick box with its label beside it. */
export function CheckBox({ id, label, checked, onChange, disabled }: { id: string; label: React.ReactNode; checked: boolean; onChange: (checked: boolean) => void; disabled?: boolean }) {
  return (
    <label htmlFor={id} className="flex items-center gap-2 text-[13px] font-bold">
      <input id={id} type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} className="size-4 accent-primary" />
      {label}
    </label>
  );
}
