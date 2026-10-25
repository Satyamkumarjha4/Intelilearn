/**
 * Unit under test: `StopControl`, what the "Stop building" button and its confirmation show while a build runs.
 *
 * Why: the lesson's active run can end (or be between two runs) while the learner is reading the question. A dialog
 * that vanishes under their cursor, or a confirm button that does nothing, is worse than telling them the build just
 * finished. The dialog belongs to the learner's action, not to the run.
 *
 * Use cases:
 * - while a run is active the button shows and confirming is allowed
 * - without a run the button is gone, and nothing is mounted unless the dialog is already open
 * - a dialog that is open stays open when the run ends or flickers away, and confirming is disabled until a run is back
 * - the words change to say the build already ended, so a disabled button is explained
 */
import { describe, expect, test } from "bun:test";

import { StopControl } from "./stop-control";

describe("of", () => {
  test("shows the button and allows confirming while a run is active", () => {
    expect(StopControl.of({ canStop: true, open: false })).toMatchObject({ showButton: true, mountDialog: true, canConfirm: true });
  });

  test("shows nothing without a run, unless the dialog is already open", () => {
    expect(StopControl.of({ canStop: false, open: false })).toMatchObject({ showButton: false, mountDialog: false, canConfirm: false });
  });

  test("keeps an open dialog mounted when the run ends, and stops it from confirming", () => {
    expect(StopControl.of({ canStop: false, open: true })).toMatchObject({ showButton: false, mountDialog: true, canConfirm: false });
  });

  test("confirms again when a run comes back while the dialog is open", () => {
    expect(StopControl.of({ canStop: true, open: true })).toMatchObject({ mountDialog: true, canConfirm: true });
  });

  test("explains a disabled confirm in words", () => {
    const ended = StopControl.of({ canStop: false, open: true }).description;
    const running = StopControl.of({ canStop: true, open: true }).description;

    expect(ended).toContain("nothing left to stop");
    expect(running).toContain("Nothing is lost");
    expect(ended).not.toBe(running);
  });
});
