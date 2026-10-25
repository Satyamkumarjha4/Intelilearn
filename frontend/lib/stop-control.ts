/** What the "Stop building" button and its confirmation show. The dialog follows the learner's action, not the run:
 *  the run can end or be replaced while they read the question, and the dialog must not vanish under their cursor. */
export class StopControl {
  static readonly ASK = "We'll pause where we are. Nothing is lost, and you can pick it up again with Retry.";
  static readonly ENDED = "This step just finished, so there is nothing left to stop.";

  static of({ canStop, open }: { canStop: boolean; open: boolean }) {
    return {
      /** The button is only offered while there is a run to stop. */
      showButton: canStop,
      /** An open dialog stays, even when the run it was about has gone. */
      mountDialog: canStop || open,
      canConfirm: canStop,
      description: canStop ? StopControl.ASK : StopControl.ENDED,
    };
  }
}
