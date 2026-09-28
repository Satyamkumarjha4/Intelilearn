import { Label } from "@/components/ui/label";

type FormFieldProps = {
  id: string;
  label: string;
  hint?: string;
  errors?: string[];
  children: React.ReactNode;
};

/** Label + control + hint or error text. */
export function FormField({ id, label, hint, errors, children }: FormFieldProps) {
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {errors?.length ? (
        <p id={`${id}-error`} className="text-sm text-destructive">
          {errors.join(" ")}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-sm text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
