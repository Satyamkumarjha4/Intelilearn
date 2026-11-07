import { CheckoutUnavailable } from "./checkout-contract";

/** Puts a `<script>` in the page and says when it has loaded or failed. */
export type ScriptInjector = (src: string, onload: () => void, onerror: () => void) => void;

/** The browser's way of loading a script: a `<script async>` at the end of the body, removed again if it fails (so a
 *  second try is a clean one). `doc` is injected so the class can be tested without a browser. */
export class BrowserScripts {
  constructor(private readonly doc: Pick<Document, "createElement" | "body"> | (() => Pick<Document, "createElement" | "body">) = () => document) {}

  inject: ScriptInjector = (src, onload, onerror) => {
    const doc = typeof this.doc === "function" ? this.doc() : this.doc;
    const script = doc.createElement("script");
    script.src = src;
    script.async = true;
    script.onload = () => onload();
    script.onerror = () => {
      script.remove();
      onerror();
    };
    doc.body.appendChild(script);
  };
}

/**
 * Loads a provider's script when it is first needed, once. A second call while it loads shares the first; a call once it
 * has loaded does nothing; a failure is forgotten, so the next try loads it again. `loaded` says whether the script has
 * already done its work (its global exists), which also covers a page that has it from somewhere else.
 */
export class ScriptLoader {
  private readonly loading = new Map<string, Promise<void>>();

  constructor(private readonly inject: ScriptInjector = new BrowserScripts().inject) {}

  load(src: string, loaded: () => boolean): Promise<void> {
    if (loaded()) return Promise.resolve();
    const existing = this.loading.get(src);
    if (existing) return existing;
    const attempt = new Promise<void>((resolve, reject) => {
      this.inject(
        src,
        () => (loaded() ? resolve() : reject(new CheckoutUnavailable("The payment window did not start."))),
        () => reject(new CheckoutUnavailable("The payment window could not be loaded.")),
      );
    });
    const guarded = attempt.catch((error) => {
      this.loading.delete(src);
      throw error;
    });
    this.loading.set(src, guarded);
    return guarded;
  }
}
