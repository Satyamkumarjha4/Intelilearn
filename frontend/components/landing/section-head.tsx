/** The eyebrow, heading and optional line that open a section of the landing page. */
export function SectionHead({ eyebrow, title, text, tone = "default" }: { eyebrow: string; title: string; text?: string; tone?: "default" | "onPanel" }) {
  const onPanel = tone === "onPanel";
  return (
    <div className="flex max-w-[680px] flex-col gap-2.5">
      <span className={`text-base font-extrabold ${onPanel ? "text-primary-foreground dark:text-marigold-text" : "text-primary-text"}`}>{eyebrow}</span>
      <h2 className="text-[clamp(30px,4vw,44px)] leading-[1.1] font-semibold">{title}</h2>
      {text ? <p className="text-[19px] text-muted-foreground">{text}</p> : null}
    </div>
  );
}
