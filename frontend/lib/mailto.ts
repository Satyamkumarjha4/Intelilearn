/** Links that open the mail app. They don't work for everyone (no mail app set up), so the pages also show the address
 *  and the subject as text to copy. */
export class Mailto {
  static link(email: string, subject: string, body = ""): string {
    const query = [`subject=${encodeURIComponent(subject)}`, ...(body ? [`body=${encodeURIComponent(body)}`] : [])];
    return `mailto:${email}?${query.join("&")}`;
  }
}
