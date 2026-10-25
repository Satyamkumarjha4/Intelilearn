type Jar = { cookie: string };

/** The cookie that says the learner is in the last step of the setup, so the route guard lets a refresh stay there. */
export class SetupMarker {
  static readonly COOKIE = "lc_setting_up";

  constructor(private readonly jar: Jar | undefined = SetupMarker.documentJar()) {}

  begin(): void {
    this.write(`${SetupMarker.COOKIE}=1; path=/; SameSite=Lax`);
  }

  end(): void {
    this.write(`${SetupMarker.COOKIE}=; path=/; SameSite=Lax; max-age=0`);
  }

  private write(cookie: string): void {
    try {
      if (this.jar) this.jar.cookie = cookie;
    } catch {
      // blocked: a refresh on the last step then goes to the lessons, and the topic is chosen again
    }
  }

  private static documentJar(): Jar | undefined {
    return typeof document === "undefined" ? undefined : document;
  }
}
