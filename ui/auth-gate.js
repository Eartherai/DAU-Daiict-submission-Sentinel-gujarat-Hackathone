/* Pure sign-in gate logic, factored out of app.js so it has no DOM
 * dependency and can be exercised by a plain `node --test` run.
 *
 * A bearer token authenticates whoever holds it — that is what "bearer"
 * means. Asking for an Officer ID at sign-in does not add a second secret;
 * it catches a wrong token pasted from a clipboard or a shared token entered
 * under the wrong name. The server principal remains authoritative. */
export function officerIdMismatch(enteredOfficerId, principal) {
  const entered = String(enteredOfficerId || "").trim().toLowerCase();
  const actual = String((principal && principal.user_id) || "")
    .trim().toLowerCase();
  if (!entered || !actual) return true;
  return entered !== actual;
}
