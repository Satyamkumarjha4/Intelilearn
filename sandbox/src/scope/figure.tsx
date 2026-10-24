import React from "react";

type Media = { url: string; alt: string; caption: string; attribution: string; license: string; source_url: string };

/** The only way to show an image or GIF: by asset id, with the caption and attribution the licence asks for. */
export function Figure({ asset }: { asset: string }) {
  const lesson = (globalThis as unknown as { __LESSON__?: { media?: Record<string, Media> } }).__LESSON__;
  const media = lesson?.media?.[asset];
  if (!media) return <p className="text-sm text-muted-foreground">(image unavailable)</p>;
  return (
    <figure className="flex flex-col gap-2">
      <img src={media.url} alt={media.alt} className="max-h-96 w-full rounded-lg object-contain" loading="lazy" />
      <figcaption className="text-sm text-muted-foreground">
        {media.caption}
        {media.attribution && <span> · {media.attribution}</span>}
        {media.license && <span> · {media.license}</span>}
      </figcaption>
    </figure>
  );
}
